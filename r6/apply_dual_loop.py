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
FILES = [BLE, GPU, MOD, CFG, CMD, TYPES, VIEW]

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
         "    pub pump_start_temp: u8,\n    pub pump_stop_temp: u8,\n    pub pump_turbo_temp: u8,\n", "telemetry field")
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
         "            pump_stop_temp: self.state.pump_stop_temp.load(Ordering::SeqCst),\n",
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
         "  pump_start_temp?: number;\n  pump_stop_temp?: number;\n", "frontend type")

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
         "const handleUpdatePumpThresholds = async (startTemp: number, turboTemp: number, committed: boolean, stopOverride?: number) => {",
         "frontend handler")
    edit(VIEW,
         """    isDraggingPumpRef.current = false;
    setCoolerData((prev) => ({
      ...prev,
      pump_start_temp: startTemp,
""",
         """    isDraggingPumpRef.current = false;
    const stopTemp = Math.max(30, Math.min(startTemp - 3, stopOverride ?? coolerData.pump_stop_temp ?? 47));
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
         """          onPumpThresholdsChange={handleUpdatePumpThresholds}
        />

        {/* 4. 手动精调""",
         """          onPumpThresholdsChange={handleUpdatePumpThresholds}
        />

        {/* Independent stop threshold for the GM6IX8X dual-source strategy */}
        <div style={{ padding: '12px 16px', border: '1px solid var(--border-subtle)', borderRadius: 12 }}>
          <label htmlFor="dualloop-stop" style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
            <span>独立停泵阈值（GM6IX8X 双热源策略）</span>
            <strong>{coolerData.pump_stop_temp ?? 47}°C</strong>
          </label>
          <input id="dualloop-stop" type="range" min={30}
            max={Math.max(30, (coolerData.pump_start_temp ?? 55) - 3)}
            value={coolerData.pump_stop_temp ?? 47}
            onPointerDown={() => { isDraggingPumpRef.current = true; }}
            onChange={(e) => setCoolerData(prev => ({ ...prev, pump_stop_temp: Number(e.target.value) }))}
            onPointerUp={(e) => handleUpdatePumpThresholds(coolerData.pump_start_temp ?? 55, coolerData.pump_turbo_temp ?? 90, true, Number(e.currentTarget.value))}
            onKeyUp={(e) => handleUpdatePumpThresholds(coolerData.pump_start_temp ?? 55, coolerData.pump_turbo_temp ?? 90, true, Number(e.currentTarget.value))}
            onBlur={(e) => { if (isDraggingPumpRef.current) handleUpdatePumpThresholds(coolerData.pump_start_temp ?? 55, coolerData.pump_turbo_temp ?? 90, true, Number(e.currentTarget.value)); }}
            style={{ width: '100%' }}
          />
          <div style={{ fontSize: 11, opacity: 0.72 }}>启泵与狂暴使用上方滑块；CPU 启泵 +5°C、停泵 +3°C，两处均降温才停泵。</div>
        </div>

        {/* 4. 手动精调""", "stop slider")

    edit(GPU, "impl GpuBridge {",
         """fn find_nvidia_smi_command() -> Command {
    let windows = std::env::var_os("WINDIR")
        .map(|p| std::path::PathBuf::from(p).join("System32").join("nvidia-smi.exe"));
    let nvidia = std::env::var_os("ProgramFiles")
        .map(|p| std::path::PathBuf::from(p).join("NVIDIA Corporation").join("NVSMI").join("nvidia-smi.exe"));
    for path in [windows, nvidia].into_iter().flatten() {
        if path.is_file() {
            let mut cmd = Command::new(path);
            cmd.creation_flags(CREATE_NO_WINDOW);
            return cmd;
        }
    }
    let mut cmd = Command::new("nvidia-smi");
    cmd.creation_flags(CREATE_NO_WINDOW);
    cmd
}

impl GpuBridge {""", "NVIDIA executable lookup")
    edit(GPU,
         """                let output = Command::new("nvidia-smi")
                    .creation_flags(CREATE_NO_WINDOW)
""",
         """                let output = find_nvidia_smi_command()
""", "GPU command path")
    edit(GPU, "            temp: AtomicU32::new(35),",
         "            temp: AtomicU32::new(0),", "GPU sentinel")
    edit(GPU,
         """                if let Ok(out) = output {
                    if out.status.success() {
                        consecutive_failures = 0;
                        let text = String::from_utf8_lossy(&out.stdout);""",
         """                if let Ok(out) = output {
                    if out.status.success() {
                        let text = String::from_utf8_lossy(&out.stdout);""",
         "GPU command success")
    edit(GPU,
         """                        if parts.len() >= 7 {
                            let name = parts[0];""",
         """                        if parts.len() >= 7 {
                            match parts[3].parse::<u32>() {
                                Ok(t) if (10..=110).contains(&t) => {
                                    inner.temp.store(t, Ordering::SeqCst);
                                    consecutive_failures = 0;
                                },
                                _ => consecutive_failures = consecutive_failures.saturating_add(1),
                            }
                            let name = parts[0];""", "GPU parse")
    edit(GPU,
         """                            if let Ok(t) = parts[3].parse::<u32>() {
                                inner.temp.store(t, Ordering::SeqCst);
                            }
""", "", "GPU duplicate parse")
    edit(GPU,
         """                                }
                            }
                        }
                    } else {
                        consecutive_failures = consecutive_failures.saturating_add(1);
                    }
                } else {
                    consecutive_failures = consecutive_failures.saturating_add(1);
                }
            }
        });
""",
         """                                }
                            }
                        } else {
                            consecutive_failures = consecutive_failures.saturating_add(1);
                        }
                    } else {
                        consecutive_failures = consecutive_failures.saturating_add(1);
                    }
                } else {
                    consecutive_failures = consecutive_failures.saturating_add(1);
                }
                if consecutive_failures >= 3 {
                    inner.temp.store(0, Ordering::SeqCst); // unavailable, not fake 35°C
                }
            }
        });
""", "GPU sensor stale")
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
