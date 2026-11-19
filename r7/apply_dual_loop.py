#!/usr/bin/env python3
"""Apply GM6IX8X dual-source policy to pinned OpenRevo source. Dry-run by default."""
from pathlib import Path
import argparse
import shutil
import sys

CORE = Path("src-tauri/src")
BLE = CORE / "driver/ble_cooler.rs"
GPU = CORE / "driver/gpu_bridge.rs"
MOD = CORE / "driver/mod.rs"
CFG = CORE / "system/config.rs"
CMD = Path("src-tauri/src/commands/cooler_cmd.rs")
TYPES = Path("src/components/water_cooler/coolerTypes.ts")
VIEW = Path("src/components/WaterCoolerView.tsx")
NEW = CORE / "driver/dual_loop_policy.rs"
FILES = [BLE, MOD, CFG, CMD, TYPES, VIEW]

def change(original, old, new, label):
    count = original.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected 1 anchor, found {count}; source unchanged")
    return original.replace(old, new, 1)

def patch(root):
    d = {p: (root / p).read_text(encoding="utf-8") for p in FILES}
    def edit(p, old, new, label):
        d[p] = change(d[p], old, new, label)

    edit(MOD, "pub mod ble_cooler;\n",
         "pub mod ble_cooler;\npub mod dual_loop_policy;\n", "module")
    edit(CFG,
         "    pub cooler_pump_start_temp: u8, // default 55°C (Stop/Standard pump threshold)\n",
         "    pub cooler_pump_start_temp: u8, // default 55°C (Stop/Standard pump threshold)\n"
         '    #[serde(default = "default_cooler_pump_stop_temp")]\n'
         "    pub cooler_pump_stop_temp: u8,\n", "config field")
    edit(CFG, "fn default_cooler_pump_start_temp() -> u8 { 55 }\n",
         "fn default_cooler_pump_start_temp() -> u8 { 55 }\n"
         "fn default_cooler_pump_stop_temp() -> u8 { 47 }\n", "config default fn")
    edit(CFG, "            cooler_pump_start_temp: 55,\n",
         "            cooler_pump_start_temp: 55,\n"
         "            cooler_pump_stop_temp: 47,\n", "config default")

    edit(BLE, "    pub pump_start_temp: AtomicU8, // 启泵阈值（默认 55°C）\n",
         "    pub pump_start_temp: AtomicU8, // 启泵阈值（默认 55°C）\n"
         "    pub pump_stop_temp: AtomicU8,\n", "controller stop field")
    edit(BLE, "    pub pump_start_temp: u8,\n    pub pump_turbo_temp: u8,\n",
         "    pub pump_start_temp: u8,\n    pub pump_stop_temp: u8,\n    pub pump_turbo_temp: u8,\n    pub dual_loop_model: bool,\n", "telemetry field")
    edit(BLE, "        cooler.state.pump_start_temp.store(start_t, Ordering::SeqCst);\n",
         "        cooler.state.pump_start_temp.store(start_t, Ordering::SeqCst);\n"
         "        cooler.state.pump_stop_temp.store("
         "cfg.cooler_pump_stop_temp.clamp(30, start_t.saturating_sub(3)), Ordering::SeqCst);\n",
         "startup restore")
    edit(BLE, "                pump_start_temp: AtomicU8::new(55),\n",
         "                pump_start_temp: AtomicU8::new(55),\n"
         "                pump_stop_temp: AtomicU8::new(47),\n", "new state")
    edit(BLE, "            pump_start_temp: self.state.pump_start_temp.load(Ordering::SeqCst),\n",
         "            pump_start_temp: self.state.pump_start_temp.load(Ordering::SeqCst),\n"
         "            pump_stop_temp: self.state.pump_stop_temp.load(Ordering::SeqCst),\n"
         "            dual_loop_model: super::dual_loop_policy::is_active_machine(),\n",
         "telemetry getter")
    edit(BLE,
         "pub fn set_pump_thresholds(&self, start_temp: u8, turbo_temp: u8) -> CoolerTelemetry {",
         "pub fn set_pump_thresholds(&self, start_temp: u8, stop_temp: u8, turbo_temp: u8) -> CoolerTelemetry {",
         "set signature")
    edit(BLE,
         """        self.state.pump_start_temp.store(start_clamped, Ordering::SeqCst);
        self.state.pump_turbo_temp.store(turbo_clamped, Ordering::SeqCst);
""",
         """        let stop_clamped = stop_temp.clamp(30, start_clamped.saturating_sub(3));
        self.state.pump_start_temp.store(start_clamped, Ordering::SeqCst);
        self.state.pump_stop_temp.store(stop_clamped, Ordering::SeqCst);
        self.state.pump_turbo_temp.store(turbo_clamped, Ordering::SeqCst);
""", "threshold clamp")
    edit(BLE,
         """        cfg.cooler_pump_start_temp = start_clamped;
        cfg.cooler_pump_turbo_temp = turbo_clamped;
""",
         """        cfg.cooler_pump_start_temp = start_clamped;
        cfg.cooler_pump_stop_temp = stop_clamped;
        cfg.cooler_pump_turbo_temp = turbo_clamped;
""", "threshold persist")
    edit(BLE,
         """        if self.state.strategy.read().as_str() == "smart" {
            let max_temp = get_current_max_temp();
            let cur_tier = CoolerPumpTier::from_u8(self.state.pump_tier.load(Ordering::SeqCst));
            let next_tier = calculate_pump_tier_with_hysteresis(max_temp, cur_tier, start_clamped, turbo_clamped);
""",
         """        // Dual-loop mode uses sustained temperature dwell in the supervisor.
        if self.state.strategy.read().as_str() == "smart" && !super::dual_loop_policy::is_active_machine() {
            let max_temp = get_current_max_temp();
            let cur_tier = CoolerPumpTier::from_u8(self.state.pump_tier.load(Ordering::SeqCst));
            let next_tier = calculate_pump_tier_with_hysteresis(max_temp, cur_tier, start_clamped, turbo_clamped);
""", "no premature stop")
    edit(BLE,
         """                let next_tier = calculate_pump_tier_with_hysteresis(max_temp, cur_tier, start_temp, turbo_temp);
                let target_fan = evaluate_cooler_fan_duty_smooth(max_temp);
""",
         """                let (next_tier, target_fan) = if super::dual_loop_policy::is_active_machine() {
                    super::dual_loop_policy::evaluate_live(
                        start_temp,
                        self.state.pump_stop_temp.load(Ordering::SeqCst),
                        turbo_temp,
                    )
                } else {
                    (calculate_pump_tier_with_hysteresis(max_temp, cur_tier, start_temp, turbo_temp),
                     evaluate_cooler_fan_duty_smooth(max_temp))
                };
""", "main supervisor")

    edit(CMD,
         """pub fn set_water_cooler_pump_thresholds(start_temp: u8, turbo_temp: u8) -> CoolerTelemetry {
    crate::log_info!("COOLER_CMD", "[IPC] set_water_cooler_pump_thresholds: start_temp={}, turbo_temp={}", start_temp, turbo_temp);
    let cooler = crate::driver::ble_cooler::get_global_cooler();
    cooler.set_pump_thresholds(start_temp, turbo_temp)
}""",
         """pub fn set_water_cooler_pump_thresholds(start_temp: u8, stop_temp: Option<u8>, turbo_temp: u8) -> CoolerTelemetry {
    let stop = stop_temp.unwrap_or(start_temp.saturating_sub(8));
    crate::log_info!("COOLER_CMD", "[IPC] cooler start={}, stop={}, turbo={}", start_temp, stop, turbo_temp);
    let cooler = crate::driver::ble_cooler::get_global_cooler();
    cooler.set_pump_thresholds(start_temp, stop, turbo_temp)
}""", "IPC command")
    edit(TYPES, "  pump_start_temp?: number;\n",
         "  pump_start_temp?: number;\n  pump_stop_temp?: number;\n  dual_loop_model?: boolean;\n", "frontend type")

    edit(VIEW, "    pump_start_temp: 55,\n    pump_turbo_temp: 90,\n",
         "    pump_start_temp: 55,\n    pump_stop_temp: 47,\n    pump_turbo_temp: 90,\n",
         "frontend default")
    edit(VIEW,
         "            pump_start_temp: isDraggingPumpRef.current ? prev.pump_start_temp : (res.pump_start_temp ?? prev.pump_start_temp),\n",
         "            pump_start_temp: isDraggingPumpRef.current ? prev.pump_start_temp : (res.pump_start_temp ?? prev.pump_start_temp),\n"
         "            pump_stop_temp: isDraggingPumpRef.current ? prev.pump_stop_temp : (res.pump_stop_temp ?? prev.pump_stop_temp),\n",
         "frontend polling")
    edit(VIEW,
         "const handleUpdatePumpThresholds = async (startTemp: number, turboTemp: number, committed: boolean) => {",
         "const handleUpdatePumpThresholds = async (stopTemp: number, startTemp: number, turboTemp: number, committed: boolean) => {",
         "frontend handler")
    edit(VIEW,
         """    isDraggingPumpRef.current = false;
    setCoolerData((prev) => ({
      ...prev,
      pump_start_temp: startTemp,
""",
         """    isDraggingPumpRef.current = false;
    setCoolerData((prev) => ({
      ...prev,
      pump_stop_temp: stopTemp,
      pump_start_temp: startTemp,
""", "frontend handler state")
    edit(VIEW, """        startTemp,
        turboTemp,
      });
""",
         """        startTemp,
        stopTemp,
        turboTemp,
      });
""", "frontend IPC")
    edit(VIEW,
         "          pumpStartTemp={coolerData.pump_start_temp ?? 55}\n",
         "          pumpStartTemp={coolerData.pump_start_temp ?? 55}\n"
         "          pumpStopTemp={coolerData.pump_stop_temp ?? 47}\n"
         "          showStopHandle={coolerData.dual_loop_model}\n",
         "restore r5 vertical stop line")


    # In the new CPU-cooled profile, initial (re)connection primes Standard tier.
    # Never use a transient max(CPU,GPU) reading to initialize Turbo on the new model.
    edit(BLE,
         '        "smart" => {\n            let cur_temp = get_current_max_temp();',
         '        "smart" if super::dual_loop_policy::is_active_machine() => (CoolerPumpTier::Standard as u8, 42),\n'
         '        "smart" => {\n            let cur_temp = get_current_max_temp();',
         "safe initial smart policy")

    edit(BLE,
         '    pub fn resume_after_wake(&self) {\n',
         '    pub fn resume_after_wake(&self) {\n'
         '        if super::dual_loop_policy::is_active_machine() { super::dual_loop_policy::reset_live(); }\n',
         "reset after resume")

    edit(BLE,
         '        *self.state.strategy.write() = strategy.to_string();\n',
         '        *self.state.strategy.write() = strategy.to_string();\n'
         '        if strategy == "smart" && super::dual_loop_policy::is_active_machine() { super::dual_loop_policy::reset_live(); }\n',
         "reset on smart strategy selection")
    return d

def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--source", required=True)
    a.add_argument("--apply", action="store_true")
    o = a.parse_args()
    root = Path(o.source).resolve()
    if not (root / "src-tauri/Cargo.toml").exists():
        raise ValueError("Not an OpenRevo checkout")
    if (root / NEW).exists():
        raise ValueError("Dual-loop module already exists")
    modified = patch(root)
    print(f"Validated {len(modified)} source files and 1 Rust module")
    if not o.apply:
        print("Dry-run passed; use --apply to write")
        return
    backup = root / ".dualloop-r6-backup"
    if backup.exists():
        raise ValueError("Refusing to overwrite prior backup")
    for f in modified:
        (backup / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / f, backup / f)
    for f, contents in modified.items():
        (root / f).write_text(contents, encoding="utf-8")
    (root / NEW).write_text(
        (Path(__file__).resolve().parent / "dual_loop_policy.rs").read_text(encoding="utf-8"),
        encoding="utf-8"
    )
    print(f"Applied patch, originals in {backup}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
