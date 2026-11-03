#!/usr/bin/env python3
"""GM6PX8X-only GPU water-cooler anti-cycling overlay.

Applies AFTER scripts/apply_fixes.py and upstream NVML import.
Preserves legacy CPU/GPU max behavior for every other BIOS model.
Source edits are guarded; unrecognized upstream changes stop the build.
"""
import sys
from pathlib import Path

def replace_one(path, old, new, label):
    data = path.read_text(encoding="utf-8")
    matches = data.count(old)
    if matches != 1:
        raise SystemExit(f"{label}: expected exactly one source anchor, got {matches} in {path}")
    path.write_text(data.replace(old,new,1), encoding="utf-8", newline="\n")
    print("Patched:",label)

def main():
    root=Path(sys.argv[1]).resolve()
    cooler=root/"src-tauri/src/driver/ble_cooler.rs"
    ui=root/"src/components/WaterCoolerView.tsx"
    types=root/"src/components/water_cooler/coolerTypes.ts"
    header=root/"src/components/water_cooler/CoolerHeaderTelemetry.tsx"
    preset=root/"src/components/water_cooler/CoolerPresetCards.tsx"
    for path in (cooler,ui,types,header,preset):
        if not path.exists():
            raise SystemExit(f"Source missing: {path}")

    existing=cooler.read_text(encoding="utf-8")
    start=existing.find("// Existing BLE callers keep this name; smart mode now uses GPU-first mapping.")
    end=existing.find("\npub fn calculate_strategy_params(",start)
    if start<0 or end<0 or existing.count("mod gpu_first_cooler_temp_tests")!=1:
        raise SystemExit("GPU-first v0.9.3 overlay not found")
    old=existing[start:end]
    new=r'''/// Enable this topology-specific strategy only on physical GM6PX8X machines.
/// Do not use a user-editable model alias or project ID for cooling topology.
pub fn is_gm6px8x_gpu_only_cooler() -> bool {
    static GPU_ONLY: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *GPU_ONLY.get_or_init(|| {
        let bios_model = crate::system::model_engine::get_device_full_name();
        let matched = bios_model.to_ascii_uppercase().contains("GM6PX8X");
        crate::log_info!("BLE_COOLER", "GM6PX8X GPU-only water loop: enabled={}, BIOS model={}", matched, bios_model);
        matched
    })
}

/// Returns actual measured temperature (0 means unavailable on GM6PX8X).
/// Every other notebook retains upstream max(CPU,GPU) control temperature.
pub fn get_current_max_temp() -> u8 {
    let cpu_t = crate::system::cpu_monitor::get_global_cpu_monitor().get_temp().clamp(0, 110) as u8;
    let gpu_t = get_valid_gpu_temp().unwrap_or(0);
    if is_gm6px8x_gpu_only_cooler() {
        gpu_t
    } else {
        cpu_t.max(gpu_t).max(30)
    }
}

fn get_valid_gpu_temp() -> Option<u8> {
    let gpu = crate::driver::gpu_bridge::get_global_gpu();
    let bridge = gpu.lock();
    if bridge.get_gpu_count() == 0 { return None; }
    let temp = bridge.get_temp(0);
    if (10..=110).contains(&temp) { Some(temp as u8) } else { None }
}

/// A stateful pump anti-cycling gate. Construct one instance per BLE connection.
/// All timers are monotonic; no delayed timer threads or extra hardware writes.
struct Gm6px8xPumpGuard {
    last_tier: CoolerPumpTier,
    on_since: Option<Instant>,
    off_since: Option<Instant>,
    warm_since: Option<Instant>,
    cool_since: Option<Instant>,
}
impl Gm6px8xPumpGuard {
    fn new(initial: CoolerPumpTier, now: Instant) -> Self {
        Self {
            last_tier: initial,
            on_since: if initial == CoolerPumpTier::Stop { None } else { Some(now) },
            off_since: None, // Cold boot should not suppress the first legitimate start.
            warm_since: None,
            cool_since: None,
        }
    }

    fn transition(&mut self, new_tier: CoolerPumpTier, now: Instant) -> CoolerPumpTier {
        if new_tier != self.last_tier {
            if new_tier == CoolerPumpTier::Stop {
                self.off_since = Some(now);
                self.on_since = None;
            } else if self.last_tier == CoolerPumpTier::Stop {
                self.on_since = Some(now);
                self.off_since = None;
            }
            self.last_tier = new_tier;
            self.warm_since = None;
            self.cool_since = None;
        }
        new_tier
    }

    fn next(&mut self, tier: CoolerPumpTier, temp: Option<u8>, now: Instant,
            start: u8, turbo: u8) -> CoolerPumpTier {
        // Manual commands and reconnects can alter the pump outside this state machine.
        if tier != self.last_tier {
            self.transition(tier, now);
        }
        let t = match temp {
            Some(t) => t,
            None => {
                // Sensor loss cannot itself authorize pump shutdown or restart.
                self.warm_since = None;
                self.cool_since = None;
                return tier;
            }
        };

        // Emergency GPU heat must override all timers, including the off lockout.
        if t >= turbo {
            return self.transition(CoolerPumpTier::Turbo, now);
        }
        if tier == CoolerPumpTier::Stop {
            if t >= 80 {
                return self.transition(CoolerPumpTier::Standard, now);
            }
            if t >= start {
                if self.warm_since.is_none() { self.warm_since = Some(now); }
                let sustained = self.warm_since.map(|s| now.duration_since(s) >= Duration::from_secs(15)).unwrap_or(false);
                let rested = self.off_since.map(|s| now.duration_since(s) >= Duration::from_secs(180)).unwrap_or(true);
                if sustained && rested {
                    return self.transition(CoolerPumpTier::Standard, now);
                }
            } else { self.warm_since = None; }
            return CoolerPumpTier::Stop;
        }

        // Exit turbo after its own 5 C hysteresis, without stopping the pump.
        if tier == CoolerPumpTier::Turbo && t > turbo.saturating_sub(5) {
            return CoolerPumpTier::Turbo;
        }
        if t <= start.saturating_sub(10) {
            if self.cool_since.is_none() { self.cool_since = Some(now); }
            let cooled = self.cool_since.map(|s| now.duration_since(s) >= Duration::from_secs(180)).unwrap_or(false);
            let ran_long_enough = self.on_since.map(|s| now.duration_since(s) >= Duration::from_secs(600)).unwrap_or(false);
            if cooled && ran_long_enough {
                return self.transition(CoolerPumpTier::Stop, now);
            }
        } else {
            self.cool_since = None;
        }
        self.transition(CoolerPumpTier::Standard, now)
    }
}

#[cfg(test)]
mod gpu_only_pump_guard_tests {
    use super::{CoolerPumpTier as Tier, Gm6px8xPumpGuard};
    use std::time::{Duration, Instant};

    #[test]
    fn browsing_without_gpu_heat_keeps_pump_off() {
        let now = Instant::now();
        let mut g = Gm6px8xPumpGuard::new(Tier::Stop, now);
        assert_eq!(g.next(Tier::Stop, Some(43), now+Duration::from_secs(900),55,90),Tier::Stop);
    }
    #[test]
    fn warmup_and_cooldown_have_minimum_times() {
        let now=Instant::now();
        let mut g=Gm6px8xPumpGuard::new(Tier::Stop,now);
        assert_eq!(g.next(Tier::Stop,Some(56),now,55,90),Tier::Stop);
        assert_eq!(g.next(Tier::Stop,Some(56),now+Duration::from_secs(16),55,90),Tier::Standard);
        assert_eq!(g.next(Tier::Standard,Some(44),now+Duration::from_secs(150),55,90),Tier::Standard);
        assert_eq!(g.next(Tier::Standard,Some(44),now+Duration::from_secs(590),55,90),Tier::Standard);
        assert_eq!(g.next(Tier::Standard,Some(44),now+Duration::from_secs(617),55,90),Tier::Stop);
        assert_eq!(g.next(Tier::Stop,Some(56),now+Duration::from_secs(650),55,90),Tier::Stop);
        assert_eq!(g.next(Tier::Stop,Some(56),now+Duration::from_secs(820),55,90),Tier::Standard);
    }
    #[test]
    fn gpu_overheat_overrides_timers() {
        let now=Instant::now();
        let mut g=Gm6px8xPumpGuard::new(Tier::Stop,now);
        assert_eq!(g.next(Tier::Stop,Some(82),now,55,90),Tier::Standard);
        assert_eq!(g.next(Tier::Standard,Some(94),now+Duration::from_secs(1),55,90),Tier::Turbo);
    }
    #[test]
    fn invalid_sample_cannot_toggle_pump() {
        let now=Instant::now();
        let mut stopped=Gm6px8xPumpGuard::new(Tier::Stop,now);
        let mut running=Gm6px8xPumpGuard::new(Tier::Standard,now);
        assert_eq!(stopped.next(Tier::Stop,None,now+Duration::from_secs(1000),55,90),Tier::Stop);
        assert_eq!(running.next(Tier::Standard,None,now+Duration::from_secs(1000),55,90),Tier::Standard);
    }
}'''
    replace_one(cooler,old,new,"Model-gated GPU-only control, stateful anti-cycling and tests")

    replace_one(cooler,
        '    pub pump_turbo_temp: u8,\n}\n\npub struct BleCoolerController {',
        '    pub pump_turbo_temp: u8,\n    pub gpu_only_model: bool,\n}\n\npub struct BleCoolerController {',
        "Report BIOS topology flag in telemetry")
    replace_one(cooler,
        '            pump_turbo_temp: self.state.pump_turbo_temp.load(Ordering::SeqCst),\n        }',
        '            pump_turbo_temp: self.state.pump_turbo_temp.load(Ordering::SeqCst),\n            gpu_only_model: is_gm6px8x_gpu_only_cooler(),\n        }',
        "Expose model flag to UI")

    replace_one(cooler,
        '''            let cur_temp = get_current_max_temp();
            let fan = evaluate_cooler_fan_duty_smooth(cur_temp);
            // Default smart uses hysteresis-driven standard tier
            let tier = calculate_pump_tier_with_hysteresis(cur_temp, CoolerPumpTier::Standard, pump_start_temp, pump_turbo_temp);
            (tier as u8, fan)''',
        '''            let cur_temp = get_current_max_temp();
            if is_gm6px8x_gpu_only_cooler() {
                // Connection-time only. During an active session the stateful
                // anti-cycling gate owns all pump transitions.
                let tier = if cur_temp == 0 { CoolerPumpTier::from_u8(fallback_pump) }
                    else if cur_temp >= pump_turbo_temp { CoolerPumpTier::Turbo }
                    else if cur_temp >= pump_start_temp { CoolerPumpTier::Standard }
                    else { CoolerPumpTier::Stop };
                let fan = if cur_temp == 0 { fallback_fan } else { evaluate_cooler_fan_duty_smooth(cur_temp) };
                (tier as u8, fan)
            } else {
                let fan = evaluate_cooler_fan_duty_smooth(cur_temp);
                let tier = calculate_pump_tier_with_hysteresis(cur_temp, CoolerPumpTier::Standard, pump_start_temp, pump_turbo_temp);
                (tier as u8, fan)
            }''',
        "Preserve default behavior of all other model strategies")

    replace_one(cooler,
        '''        let (target_pump, target_fan) = calculate_strategy_params(
            strategy,
            &curve_pts,
            cur_pump,
            cur_fan,
            start_t,
            turbo_t,
        );

        let pump_tier = CoolerPumpTier::from_u8(target_pump);''',
        '''        let (computed_pump, target_fan) = calculate_strategy_params(
            strategy,
            &curve_pts,
            cur_pump,
            cur_fan,
            start_t,
            turbo_t,
        );
        // On GM6PX8X, switching to smart must not bypass minimum run time.
        let target_pump = if strategy == "smart" && is_gm6px8x_gpu_only_cooler()
            && self.state.connected.load(Ordering::SeqCst) {
            self.state.pump_tier.load(Ordering::SeqCst)
        } else { computed_pump };

        let pump_tier = CoolerPumpTier::from_u8(target_pump);''',
        "Prevent GUI smart-mode toggle from bypassing pump guard")

    replace_one(cooler,
        '''        if self.state.strategy.read().as_str() == "smart" {
            let max_temp = get_current_max_temp();
            let cur_tier = CoolerPumpTier::from_u8(self.state.pump_tier.load(Ordering::SeqCst));''',
        '''        if self.state.strategy.read().as_str() == "smart" && !is_gm6px8x_gpu_only_cooler() {
            let max_temp = get_current_max_temp();
            let cur_tier = CoolerPumpTier::from_u8(self.state.pump_tier.load(Ordering::SeqCst));''',
        "Prevent threshold slider from bypassing stateful pump controller")

    replace_one(cooler,
        '''        let mut last_cmd_ms = 0u64;

        while self.state.running.load(Ordering::SeqCst)''',
        '''        let mut last_cmd_ms = 0u64;
        let mut gm6_pump_guard = Gm6px8xPumpGuard::new(
            CoolerPumpTier::from_u8(self.state.pump_tier.load(Ordering::SeqCst)),
            Instant::now()
        );

        while self.state.running.load(Ordering::SeqCst)''',
        "Initialize per-BLE-session anti-cycling guard")

    replace_one(cooler,
        '''            // 0. Smart Adaptive Temperature Linkage Strategy (CPU/GPU Max Temp with Hysteresis)
            if self.state.strategy.read().as_str() == "smart" {
                let max_temp = get_current_max_temp();
                let cur_tier = CoolerPumpTier::from_u8(self.state.pump_tier.load(Ordering::SeqCst));
                let start_temp = self.state.pump_start_temp.load(Ordering::SeqCst);
                let turbo_temp = self.state.pump_turbo_temp.load(Ordering::SeqCst);
                let next_tier = calculate_pump_tier_with_hysteresis(max_temp, cur_tier, start_temp, turbo_temp);
                let target_fan = evaluate_cooler_fan_duty_smooth(max_temp);
                let cur_fan = self.state.fan_duty.load(Ordering::SeqCst);''',
        '''            // 0. Model-specific smart temperature control (no extra BLE process).
            if self.state.strategy.read().as_str() == "smart" {
                let gm6 = is_gm6px8x_gpu_only_cooler();
                let current_temp = get_current_max_temp();
                let cur_tier = CoolerPumpTier::from_u8(self.state.pump_tier.load(Ordering::SeqCst));
                let start_temp = self.state.pump_start_temp.load(Ordering::SeqCst);
                let turbo_temp = self.state.pump_turbo_temp.load(Ordering::SeqCst);
                let next_tier = if gm6 {
                    gm6_pump_guard.next(cur_tier, get_valid_gpu_temp(), Instant::now(), start_temp, turbo_temp)
                } else {
                    calculate_pump_tier_with_hysteresis(current_temp, cur_tier, start_temp, turbo_temp)
                };
                // No valid GPU sensor sample: preserve the last fan/pump settings.
                let target_fan = if gm6 && current_temp == 0 {
                    self.state.fan_duty.load(Ordering::SeqCst)
                } else {
                    evaluate_cooler_fan_duty_smooth(current_temp)
                };
                let cur_fan = self.state.fan_duty.load(Ordering::SeqCst);''',
        "Install GM6PX8X GPU-only state machine inside BLE supervisor")

    replace_one(cooler,
        '''                        max_temp,
                        cur_tier,''',
        '''                        current_temp,
                        cur_tier,''',
        "Fix smart cooling debug temperature variable")
    replace_one(cooler,
        '''                self.state.last_applied_temp.store(max_temp, Ordering::SeqCst);
            }

            // 1. On-Change Pump & Fan control:''',
        '''                self.state.last_applied_temp.store(current_temp, Ordering::SeqCst);
            }

            // 1. On-Change Pump & Fan control:''',
        "Fix smart cooling telemetry temperature variable")

    replace_one(types,
        '  pump_turbo_temp?: number;',
        '  pump_turbo_temp?: number;\n  gpu_only_model?: boolean;',
        "Expose hardware-model gating to frontend types")
    replace_one(ui,
        '  const cpuGuard = cpuMeasured >= 95 ? cpuMeasured : cpuMeasured >= 85 ? 80 : cpuMeasured >= 75 ? 65 : cpuMeasured >= 60 ? 55 : 30;\n'
        '  const liveMaxTemp = gpuMeasured === null ? (cpuMeasured < 10 ? 65 : Math.max(30, cpuMeasured)) : Math.max(30, gpuMeasured, cpuGuard);',
        '  // Reflect backend authority: GM6PX8X uses GPU only; other models keep max(CPU,GPU).\n'
        '  const liveMaxTemp = coolerData.gpu_only_model ? (gpuMeasured ?? 0) : Math.max(30, cpuMeasured, gpuMeasured ?? 0);',
        "Align water temperature preview with BIOS topology flag")
    replace_one(header,
        '水冷智能控制温度（GPU 优先 / CPU 保护）',
        "{coolerData.gpu_only_model ? 'GPU 水冷控制温度（防频繁启停）' : '核心综合温度 max(CPU, GPU)'}",
        "Display the applicable model-specific cooling strategy")
    replace_one(header,
        '''            {liveMaxTemp} °C
            <span style={{ fontSize: '9px', color: 'var(--text-dim)', fontWeight: 500, marginLeft: '4px' }}>''',
        '''            {coolerData.gpu_only_model && !gpuTemp ? '--' : liveMaxTemp} °C
            <span style={{ fontSize: '9px', color: 'var(--text-dim)', fontWeight: 500, marginLeft: '4px' }}>''',
        "Do not display zero temperature while GPU sensor is offline")
    replace_one(preset,
        '  strategy?: string;\n  liveMaxTemp: number;',
        '  strategy?: string;\n  gpuOnlyModel?: boolean;\n  liveMaxTemp: number;',
        "Type separate strategy for model-specific UI")
    replace_one(preset,
        '  strategy,\n  liveMaxTemp,',
        '  strategy,\n  gpuOnlyModel,\n  liveMaxTemp,',
        "Read model-specific strategy prop")
    replace_one(preset,
        '依据核心温度动态调控，<strong style={{ color: \'var(--status-ok)\' }}>&lt;55°C 风扇停转</strong>',
        '依据{gpuOnlyModel ? \'GPU 温度（启停延时）\' : \'CPU/GPU 最高温度\'}动态调控，<strong style={{ color: \'var(--status-ok)\' }}>低温安静</strong>',
        "Adjust strategy description")
    replace_one(ui,
        '''          <CoolerPresetCards
          ''',
        '''          <CoolerPresetCards
          ''',
        "Check preset anchor") if False else None

    # The prop is injected between preset invocation and strategy, not globally.
    replace_one(ui,
        '''          <CoolerPresetCards
            strategy={coolerData.strategy}''',
        '''          <CoolerPresetCards
            gpuOnlyModel={coolerData.gpu_only_model}
            strategy={coolerData.strategy}''',
        "Tell preset cards whether the GM6PX8X-specific controller is active")

    print("GM6PX8X GPU-only silent-cooling overlay applied.")

if __name__=="__main__":
    main()
