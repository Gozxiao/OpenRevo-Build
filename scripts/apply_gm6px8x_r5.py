#!/usr/bin/env python3
"""r5: user-controlled independent GPU stop/start/turbo thresholds and command-state consistency.

Applies after apply_fixes.py -> apply_gm6px8x_quiet.py -> apply_gm6px8x_r4.py.
Fail closed on unexpected upstream code. No changes to other hardware modes.
"""
from pathlib import Path
import sys

def edit(path, old, new, why):
    s=path.read_text(encoding="utf-8")
    count=s.count(old)
    if count!=1:
        raise SystemExit(f"r5 patch mismatch {why}: {path}: found {count}")
    path.write_text(s.replace(old,new,1),encoding="utf-8",newline="\n")
    print("r5:",why)

def main():
    if len(sys.argv)!=2: raise SystemExit("usage: apply_gm6px8x_r5.py <openrevo-root>")
    root=Path(sys.argv[1])
    cooler=root/"src-tauri/src/driver/ble_cooler.rs"
    cfg=root/"src-tauri/src/system/config.rs"
    cmd=root/"src-tauri/src/commands/cooler_cmd.rs"
    types=root/"src/components/water_cooler/coolerTypes.ts"
    ui=root/"src/components/WaterCoolerView.tsx"
    curve=root/"src/components/water_cooler/CoolerCurvePanel.tsx"
    header=root/"src/components/water_cooler/CoolerHeaderTelemetry.tsx"
    presets=root/"src/components/water_cooler/CoolerPresetCards.tsx"
    for p in (cooler,cfg,cmd,types,ui,curve,header,presets):
        if not p.exists(): raise SystemExit("missing "+str(p))

    # 1. Persist third threshold without invalidating previous users' config.json.
    edit(cfg,
        '    pub cooler_pump_start_temp: u8, // default 55°C (Stop/Standard pump threshold)\n',
        '    pub cooler_pump_start_temp: u8, // default 55°C (Stop/Standard pump threshold)\n'
        '    #[serde(default = "default_cooler_pump_stop_temp")]\n'
        '    pub cooler_pump_stop_temp: u8, // default 47°C, GPU-only verified models\n',
        "Config field: independently persisted stop threshold")
    edit(cfg,
        'fn default_cooler_pump_start_temp() -> u8 { 55 }\n',
        'fn default_cooler_pump_start_temp() -> u8 { 55 }\n'
        'fn default_cooler_pump_stop_temp() -> u8 { 47 }\n',
        "Backward-compatible default")
    edit(cfg,
        '            cooler_pump_start_temp: 55,\n            cooler_pump_turbo_temp: 90,',
        '            cooler_pump_start_temp: 55,\n            cooler_pump_stop_temp: 47,\n            cooler_pump_turbo_temp: 90,',
        "Config::default includes the third value")

    edit(cooler,
        '    pub pump_start_temp: AtomicU8, // 启泵阈值（默认 55°C）\n',
        '    pub pump_start_temp: AtomicU8, // 启泵阈值（默认 55°C）\n'
        '    pub pump_stop_temp: AtomicU8, // 用户独立设置停泵温度（默认 47°C）\n',
        "Controller state stores stop threshold")
    edit(cooler,
        '                pump_start_temp: AtomicU8::new(55),\n',
        '                pump_start_temp: AtomicU8::new(55),\n'
        '                pump_stop_temp: AtomicU8::new(47),\n',
        "Controller initializes stop threshold")
    edit(cooler,
        '        cooler.state.pump_start_temp.store(start_t, Ordering::SeqCst);\n',
        '        cooler.state.pump_start_temp.store(start_t, Ordering::SeqCst);\n'
        '        let stop_t = cfg.cooler_pump_stop_temp.clamp(30, start_t.saturating_sub(3));\n'
        '        cooler.state.pump_stop_temp.store(stop_t, Ordering::SeqCst);\n',
        "Load independently persisted stop threshold")
    edit(cooler,
        '    pub pump_turbo_temp: u8,\n    pub gpu_only_model: bool,',
        '    pub pump_turbo_temp: u8,\n    pub pump_stop_temp: u8,\n    pub gpu_only_model: bool,',
        "Stop threshold in telemetry")
    edit(cooler,
        '            pump_turbo_temp: self.state.pump_turbo_temp.load(Ordering::SeqCst),\n            gpu_only_model:',
        '            pump_turbo_temp: self.state.pump_turbo_temp.load(Ordering::SeqCst),\n'
        '            pump_stop_temp: self.state.pump_stop_temp.load(Ordering::SeqCst),\n            gpu_only_model:',
        "Report saved stop threshold")
    edit(cooler,
        '    pub fn set_pump_thresholds(&self, start_temp: u8, turbo_temp: u8) -> CoolerTelemetry {',
        '    pub fn set_pump_thresholds(&self, start_temp: u8, stop_temp: Option<u8>, turbo_temp: u8) -> CoolerTelemetry {',
        "Accept third parameter on control API")
    edit(cooler,
        '        self.state.pump_start_temp.store(start_clamped, Ordering::SeqCst);\n'
        '        self.state.pump_turbo_temp.store(turbo_clamped, Ordering::SeqCst);',
        '        let old_stop = self.state.pump_stop_temp.load(Ordering::SeqCst);\n'
        '        let stop_clamped = stop_temp.unwrap_or(old_stop).clamp(30, start_clamped.saturating_sub(3));\n'
        '        self.state.pump_start_temp.store(start_clamped, Ordering::SeqCst);\n'
        '        self.state.pump_stop_temp.store(stop_clamped, Ordering::SeqCst);\n'
        '        self.state.pump_turbo_temp.store(turbo_clamped, Ordering::SeqCst);',
        "Validate independent thresholds before storing")
    edit(cooler,
        '        cfg.cooler_pump_start_temp = start_clamped;\n'
        '        cfg.cooler_pump_turbo_temp = turbo_clamped;',
        '        cfg.cooler_pump_start_temp = start_clamped;\n'
        '        cfg.cooler_pump_stop_temp = stop_clamped;\n'
        '        cfg.cooler_pump_turbo_temp = turbo_clamped;',
        "Persist threshold values")
    edit(cooler,
        '        self.state.pump_start_temp.store(55, Ordering::SeqCst);\n',
        '        self.state.pump_start_temp.store(55, Ordering::SeqCst);\n'
        '        self.state.pump_stop_temp.store(47, Ordering::SeqCst);\n',
        "Reset third slider with factory defaults")
    edit(cooler,
        '        cfg.cooler_pump_start_temp = 55;\n        cfg.cooler_pump_turbo_temp = 90;',
        '        cfg.cooler_pump_start_temp = 55;\n        cfg.cooler_pump_stop_temp = 47;\n'
        '        cfg.cooler_pump_turbo_temp = 90;',
        "Reset persisted stop temperature")
    edit(cmd,
        'pub fn set_water_cooler_pump_thresholds(start_temp: u8, turbo_temp: u8) -> CoolerTelemetry {',
        'pub fn set_water_cooler_pump_thresholds(start_temp: u8, stop_temp: Option<u8>, turbo_temp: u8) -> CoolerTelemetry {',
        "Expose optional independent stop value in Tauri")
    edit(cmd,
        '    cooler.set_pump_thresholds(start_temp, turbo_temp)',
        '    cooler.set_pump_thresholds(start_temp, stop_temp, turbo_temp)',
        "Pass stop threshold to controller")

    # 2. Synchronize the authoritative tier with voltage on reconnect and resume.
    old='        self.state.pump_voltage.store(target_pump, Ordering::SeqCst);\n        self.state.fan_duty.store(target_fan, Ordering::SeqCst);'
    new='        self.state.pump_tier.store(CoolerPumpTier::from_u8(target_pump) as u8, Ordering::SeqCst);\n'+old
    src=cooler.read_text(encoding="utf-8")
    if src.count(old)!=2:
        raise SystemExit(f"Expected 2 reconnect/resume writes, found {src.count(old)}")
    cooler.write_text(src.replace(old,new),encoding="utf-8",newline="\n")
    print("r5: synchronize tier and voltage on reconnect AND resume")
    edit(cooler,
        '        self.state.pump_voltage.store(pump_v, Ordering::SeqCst);\n'
        '        self.state.fan_duty.store(fan_d, Ordering::SeqCst);',
        '        self.state.pump_tier.store(CoolerPumpTier::from_u8(pump_v) as u8, Ordering::SeqCst);\n'
        '        self.state.pump_voltage.store(pump_v, Ordering::SeqCst);\n'
        '        self.state.fan_duty.store(fan_d, Ordering::SeqCst);',
        "Synchronize hardware pump tier immediately before BLE command")
    edit(cooler,
        '''        if pump_v > 0 {
            self.state.is_flow_ok.store(true, Ordering::SeqCst);
            self.state.meter_state.store(2, Ordering::SeqCst);
        }
        crate::log_info!("BLE_COOLER", "Connected! Initializing pump, fan and flow query...");''',
        '''        // Pump target != proof of measured water flow. Wait for BLE meter notifications.
        self.state.is_flow_ok.store(false, Ordering::SeqCst);
        self.state.meter_state.store(0, Ordering::SeqCst);
        crate::log_info!("BLE_COOLER", "Connected! Initializing pump, fan and flow query...");''',
        "Never fabricate a healthy flow meter reading at connect")

    # Initial BLE pump command was previously ignored on error and then dirty flag
    # cleared, causing stuck on/off until a later unrelated state change.
    edit(cooler,
        '        let _ = write_frame(&write_char, &[0xFE, 0x1C, pump_on, pump_volt, pump_duty, 0x00, 0x00, 0xEF]);',
        '''        let initial_pump_write_ok = match write_frame(&write_char, &[0xFE, 0x1C, pump_on, pump_volt, pump_duty, 0x00, 0x00, 0xEF]) {
            Ok(()) => true,
            Err(e) => {
                crate::log_warn!("BLE_COOLER", "Initial pump frame failed; queue retry: {}", e);
                false
            }
        };''',
        "Detect initial pump write failures")
    edit(cooler,
        '        self.state.params_dirty.store(false, Ordering::SeqCst);\n        self.state.led_dirty.store(false, Ordering::SeqCst);',
        '        self.state.params_dirty.store(!initial_pump_write_ok, Ordering::SeqCst);\n'
        '        self.state.led_dirty.store(false, Ordering::SeqCst);',
        "Retry failed BLE pump command rather than dropping it")

    # When an ongoing BLE pump write fails, leave the command pending so there is
    # another attempt on the next paced supervisor loop.
    edit(cooler,
        '''                if let Err(e) = write_frame(&write_char, &[0xFE, 0x1C, pump_on, pump_volt, pump_duty, 0x00, 0x00, 0xEF]) {
                    crate::log_warn!("BLE_LOOP", "[Loop Write Error] Pump write warning: {}", e);
                    if e.contains("0x80000013") {''',
        '''                if let Err(e) = write_frame(&write_char, &[0xFE, 0x1C, pump_on, pump_volt, pump_duty, 0x00, 0x00, 0xEF]) {
                    crate::log_warn!("BLE_LOOP", "[Loop Write Error] Pump write warning: {}", e);
                    self.state.params_dirty.store(true, Ordering::SeqCst);
                    if e.contains("0x80000013") {''',
        "Retry failed hardware pump writes on next loop")

    # 3. Replace over-timed r4 guard with explicit stop threshold and rare CPU guard.
    s=cooler.read_text(encoding="utf-8")
    a=s.find("/// GM6PX8X only: quick start")
    b=s.find("\npub fn calculate_strategy_params(",a)
    if a<0 or b<0 or s.count("mod gpu_only_pump_guard_tests")!=1:
        raise SystemExit("r4 GM6 pump state machine missing")
    old_guard=s[a:b]
    new_guard=r'''/// GPU-only loop on confirmed GM6PX8X hardware. All three thresholds are user editable.
/// CPU heat does not ordinarily operate this GPU water loop; only sustained critical
/// CPU temperature is a last-resort guard. EC/internal fan logic remains unchanged.
const GM6_START_HOLD_SECS: u64 = 2;
const GM6_STOP_HOLD_SECS: u64 = 15;
const GM6_MIN_ON_SECS: u64 = 30;
const GM6_MIN_OFF_SECS: u64 = 15;
const GM6_FAST_START_C: u8 = 70;
const GM6_CPU_CRITICAL_C: u8 = 97;
const GM6_CPU_GUARD_HOLD_SECS: u64 = 20;

struct Gm6px8xPumpGuard {
    last_tier: CoolerPumpTier,
    on_since: Option<Instant>,
    off_since: Option<Instant>,
    warm_since: Option<Instant>,
    cool_since: Option<Instant>,
    cpu_hot_since: Option<Instant>,
}
impl Gm6px8xPumpGuard {
    fn new(initial: CoolerPumpTier, now: Instant) -> Self {
        Self {
            last_tier: initial,
            on_since: if initial == CoolerPumpTier::Stop { None } else { Some(now) },
            off_since: None,
            warm_since: None,
            cool_since: None,
            cpu_hot_since: None,
        }
    }
    fn elapsed(now: Instant, since: Option<Instant>) -> u64 {
        since.map(|s| now.saturating_duration_since(s).as_secs()).unwrap_or(0)
    }
    fn remaining(now: Instant, since: Option<Instant>, duration: u64) -> u32 {
        duration.saturating_sub(Self::elapsed(now,since)) as u32
    }
    fn transition(&mut self, tier: CoolerPumpTier, now: Instant) -> CoolerPumpTier {
        if tier != self.last_tier {
            if tier == CoolerPumpTier::Stop {
                self.off_since=Some(now);
                self.on_since=None;
            } else if self.last_tier == CoolerPumpTier::Stop {
                self.on_since=Some(now);
                self.off_since=None;
            }
            self.warm_since=None;
            self.cool_since=None;
            self.last_tier=tier;
        }
        tier
    }
    fn next(&mut self, current: CoolerPumpTier, gpu: Option<u8>, cpu: u8, now: Instant,
        start: u8, stop: u8, turbo: u8) -> CoolerPumpTier {
        if current != self.last_tier { self.transition(current,now); }
        if cpu >= GM6_CPU_CRITICAL_C {
            if self.cpu_hot_since.is_none() {self.cpu_hot_since=Some(now);}
        } else {
            self.cpu_hot_since=None;
        }
        let cpu_guard=Self::elapsed(now,self.cpu_hot_since)>=GM6_CPU_GUARD_HOLD_SECS
            && self.cpu_hot_since.is_some();

        if let Some(t)=gpu {
            // Real GPU overheat bypasses all low-noise holdoff timers.
            if t>=turbo {return self.transition(CoolerPumpTier::Turbo,now);}
            if t>=GM6_FAST_START_C && current==CoolerPumpTier::Stop {
                return self.transition(CoolerPumpTier::Standard,now);
            }
        }
        if cpu_guard && current==CoolerPumpTier::Stop {
            return self.transition(CoolerPumpTier::Standard,now);
        }
        let t=match gpu {
            Some(t)=>t,
            None=>{
                // Never infer "cold" from absent GPU data, even during resume.
                self.warm_since=None;
                self.cool_since=None;
                return current;
            }
        };
        if current==CoolerPumpTier::Stop {
            if t<start {self.warm_since=None;return CoolerPumpTier::Stop;}
            if self.warm_since.is_none(){self.warm_since=Some(now);}
            let warm_enough=Self::elapsed(now,self.warm_since)>=GM6_START_HOLD_SECS;
            let off_enough=self.off_since.map(|_| Self::elapsed(now,self.off_since)>=GM6_MIN_OFF_SECS).unwrap_or(true);
            if warm_enough && off_enough {self.transition(CoolerPumpTier::Standard,now)}
            else {CoolerPumpTier::Stop}
        } else {
            // Respect turbo hysteresis; CPU does not cause turbo pumping.
            if current==CoolerPumpTier::Turbo && t>turbo.saturating_sub(5) {
                self.cool_since=None;
                return CoolerPumpTier::Turbo;
            }
            if cpu_guard {
                self.cool_since=None;
                return self.transition(CoolerPumpTier::Standard,now);
            }
            if t<=stop {
                if self.cool_since.is_none(){self.cool_since=Some(now);}
                let cool_enough=Self::elapsed(now,self.cool_since)>=GM6_STOP_HOLD_SECS;
                let on_enough=self.on_since.map(|_| Self::elapsed(now,self.on_since)>=GM6_MIN_ON_SECS).unwrap_or(false);
                if cool_enough && on_enough {return self.transition(CoolerPumpTier::Stop,now);}
            } else {self.cool_since=None;}
            self.transition(CoolerPumpTier::Standard,now)
        }
    }
    fn describe(&self, current: CoolerPumpTier, gpu: Option<u8>, cpu: u8, now: Instant,
        start: u8, stop: u8, turbo: u8) -> (String,u32) {
        if cpu>=GM6_CPU_CRITICAL_C && self.cpu_hot_since.is_some() {
            let remain=Self::remaining(now,self.cpu_hot_since,GM6_CPU_GUARD_HOLD_SECS);
            if remain==0 {return ("CPU 持续高温保护：已请求标准巡航（CPU 主要靠机身风冷）".into(),0);}
            return ("CPU 高温监测中（短时波动不会启泵）".into(),remain);
        }
        let Some(t)=gpu else {return ("GPU 传感器不可用：保持当前指令，请检查监控/连接".into(),0);};
        if current==CoolerPumpTier::Turbo {
            return ("GPU 高温强冷".into(),0);
        }
        if current==CoolerPumpTier::Stop {
            if t<start{return (format!("低温待机：GPU {}℃ / 启泵 {}℃",t,start),0);}
            let warm=Self::remaining(now,self.warm_since,GM6_START_HOLD_SECS);
            let lock=self.off_since.map(|_|Self::remaining(now,self.off_since,GM6_MIN_OFF_SECS)).unwrap_or(0);
            return ("达到启泵阈值，等待控制确认".into(),warm.max(lock));
        }
        if t>stop {
            return (format!("保持水泵运行：GPU {}℃，停泵阈值 {}℃",t,stop),0);
        }
        let cool=Self::remaining(now,self.cool_since,GM6_STOP_HOLD_SECS);
        let min_on=Self::remaining(now,self.on_since,GM6_MIN_ON_SECS);
        (format!("GPU ≤{}℃，等待停泵确认",stop),cool.max(min_on))
    }
}

#[cfg(test)]
mod gpu_only_pump_guard_tests {
    use super::{CoolerPumpTier as Tier,Gm6px8xPumpGuard};
    use std::time::{Duration,Instant};
    #[test]
    fn default_thresholds_start_and_stop() {
        let t=Instant::now();
        let mut g=Gm6px8xPumpGuard::new(Tier::Stop,t);
        assert_eq!(g.next(Tier::Stop,Some(43),50,t,55,47,90),Tier::Stop);
        assert_eq!(g.next(Tier::Stop,Some(55),50,t+Duration::from_secs(1),55,47,90),Tier::Stop);
        assert_eq!(g.next(Tier::Stop,Some(55),50,t+Duration::from_secs(3),55,47,90),Tier::Standard);
        assert_eq!(g.next(Tier::Standard,Some(46),50,t+Duration::from_secs(10),55,47,90),Tier::Standard);
        assert_eq!(g.next(Tier::Standard,Some(46),50,t+Duration::from_secs(33),55,47,90),Tier::Stop);
    }
    #[test]
    fn independent_stop_slider_changes_actual_shutdown() {
        let t=Instant::now();
        let mut g=Gm6px8xPumpGuard::new(Tier::Standard,t);
        assert_eq!(g.next(Tier::Standard,Some(49),50,t+Duration::from_secs(45),55,47,90),Tier::Standard);
        assert_eq!(g.next(Tier::Standard,Some(49),50,t+Duration::from_secs(46),55,50,90),Tier::Standard);
        assert_eq!(g.next(Tier::Standard,Some(49),50,t+Duration::from_secs(62),55,50,90),Tier::Stop);
    }
    #[test]
    fn emergency_gpu_heat_bypasses_off_lockout() {
        let t=Instant::now();
        let mut g=Gm6px8xPumpGuard::new(Tier::Stop,t);
        assert_eq!(g.next(Tier::Stop,Some(73),60,t,55,47,90),Tier::Standard);
        assert_eq!(g.next(Tier::Standard,Some(95),60,t+Duration::from_secs(1),55,47,90),Tier::Turbo);
    }
    #[test]
    fn browser_cpu_spike_does_not_trigger_pump() {
        let t=Instant::now();
        let mut g=Gm6px8xPumpGuard::new(Tier::Stop,t);
        assert_eq!(g.next(Tier::Stop,Some(42),98,t,55,47,90),Tier::Stop);
        assert_eq!(g.next(Tier::Stop,Some(42),56,t+Duration::from_secs(2),55,47,90),Tier::Stop);
    }
    #[test]
    fn sustained_critical_cpu_temperature_only() {
        let t=Instant::now();
        let mut g=Gm6px8xPumpGuard::new(Tier::Stop,t);
        assert_eq!(g.next(Tier::Stop,Some(42),99,t,55,47,90),Tier::Stop);
        assert_eq!(g.next(Tier::Stop,Some(42),99,t+Duration::from_secs(22),55,47,90),Tier::Standard);
    }
    #[test]
    fn invalid_gpu_sample_never_treated_as_cold() {
        let t=Instant::now();
        let mut running=Gm6px8xPumpGuard::new(Tier::Standard,t);
        assert_eq!(running.next(Tier::Standard,None,60,t+Duration::from_secs(600),55,47,90),Tier::Standard);
        let mut stopped=Gm6px8xPumpGuard::new(Tier::Stop,t);
        assert_eq!(stopped.next(Tier::Stop,None,60,t+Duration::from_secs(600),55,47,90),Tier::Stop);
    }
}'''
    cooler.write_text(s[:a]+new_guard+s[b:],encoding="utf-8",newline="\n")
    print("r5: independent threshold state machine with 6 executable Rust tests")

    edit(cooler,
        '''                    gm6_pump_guard.next(cur_tier, gpu_temp, now, start_temp, turbo_temp)''',
        '''                    let stop_temp = self.state.pump_stop_temp.load(Ordering::SeqCst);
                    let cpu_temp = crate::system::cpu_monitor::get_global_cpu_monitor().get_temp().clamp(0, 110) as u8;
                    gm6_pump_guard.next(cur_tier, gpu_temp, cpu_temp, now, start_temp, stop_temp, turbo_temp)''',
        "Water cooler loop uses all 3 user settings and CPU emergency guard")
    edit(cooler,
        '''                    let (phase,remaining) = gm6_pump_guard.describe(next_tier,gpu_temp,now,start_temp,turbo_temp);''',
        '''                    let stop_temp = self.state.pump_stop_temp.load(Ordering::SeqCst);
                    let cpu_temp = crate::system::cpu_monitor::get_global_cpu_monitor().get_temp().clamp(0, 110) as u8;
                    let (phase,remaining) = gm6_pump_guard.describe(next_tier,gpu_temp,cpu_temp,now,start_temp,stop_temp,turbo_temp);''',
        "Show actual configured stop temperature in backend diagnostics")

    # 4. Frontend values are committed together; old two-slider API stays backward-compatible.
    edit(types,
        '  pump_start_temp?: number;\n',
        '  pump_start_temp?: number;\n  pump_stop_temp?: number;\n',
        "Frontend type for stop slider")
    edit(ui,
        '    pump_start_temp: 55,\n    pump_turbo_temp: 90,',
        '    pump_start_temp: 55,\n    pump_stop_temp: 47,\n    pump_turbo_temp: 90,',
        "Initial UI model includes stop threshold")
    edit(ui,
        '''const handleUpdatePumpThresholds = async (startTemp: number, turboTemp: number, committed: boolean) => {''',
        '''const handleUpdatePumpThresholds = async (stopTemp: number, startTemp: number, turboTemp: number, committed: boolean) => {''',
        "Three slider callback values")
    edit(ui,
        '''      pump_start_temp: startTemp,
      pump_turbo_temp: turboTemp,''',
        '''      pump_start_temp: startTemp,
      pump_stop_temp: stopTemp,
      pump_turbo_temp: turboTemp,''',
        "Optimistic UI saves third threshold")
    edit(ui,
        '''        startTemp,
        turboTemp,''',
        '''        startTemp,
        stopTemp,
        turboTemp,''',
        "Transmit three temperature thresholds to Tauri")
    edit(ui,
        '          pumpStartTemp={coolerData.pump_start_temp ?? 55}\n',
        '          pumpStartTemp={coolerData.pump_start_temp ?? 55}\n'
        '          pumpStopTemp={coolerData.pump_stop_temp ?? 47}\n'
        '          gpuOnlyModel={coolerData.gpu_only_model}\n',
        "Pass stop threshold to chart for supported GPU-only machine")

    edit(curve,
        '  pumpStartTemp?: number;\n  pumpTurboTemp?: number;',
        '  pumpStartTemp?: number;\n  pumpStopTemp?: number;\n  gpuOnlyModel?: boolean;\n  pumpTurboTemp?: number;',
        "Add third control and model-specific visibility props")
    edit(curve,
        'onPumpThresholdsChange?: (startTemp: number, turboTemp: number, committed: boolean) => void;',
        'onPumpThresholdsChange?: (stopTemp: number, startTemp: number, turboTemp: number, committed: boolean) => void;',
        "Three temperature callback type")
    edit(curve,
        '  pumpStartTemp,\n  pumpTurboTemp,',
        '  pumpStartTemp,\n  pumpStopTemp,\n  gpuOnlyModel,\n  pumpTurboTemp,',
        "Read stop threshold")
    edit(curve,
        '''  const [localPumpStart, setLocalPumpStart] = useState<number>(pumpStartTemp ?? 55);''',
        '''  const [localPumpStart, setLocalPumpStart] = useState<number>(pumpStartTemp ?? 55);
  const [localPumpStop, setLocalPumpStop] = useState<number>(pumpStopTemp ?? 47);''',
        "Third slider state")
    edit(curve,
        '''  const [activeDragPump, setActiveDragPump] = useState<'start' | 'turbo' | null>(null);''',
        '''  const [activeDragPump, setActiveDragPump] = useState<'stop' | 'start' | 'turbo' | null>(null);''',
        "Support the third drag handle")
    edit(curve,
        '''  const [draggingFloatStart, setDraggingFloatStart] = useState<number | null>(null);''',
        '''  const [draggingFloatStart, setDraggingFloatStart] = useState<number | null>(null);
  const [draggingFloatStop, setDraggingFloatStop] = useState<number | null>(null);''',
        "Smooth stop slider drag")
    edit(curve,
        '''  useEffect(() => {
    if (!isDraggingRef.current && pumpTurboTemp !== undefined) {''',
        '''  useEffect(() => {
    if (!isDraggingRef.current && pumpStopTemp !== undefined) setLocalPumpStop(pumpStopTemp);
  }, [pumpStopTemp]);
  useEffect(() => {
    if (!isDraggingRef.current && pumpTurboTemp !== undefined) {''',
        "Synchronize stop slider with persisted setting")
    edit(curve,
        '''  const effectiveStart = draggingFloatStart ?? localPumpStart;''',
        '''  const effectiveStart = draggingFloatStart ?? localPumpStart;
  const effectiveStop = draggingFloatStop ?? localPumpStop;''',
        "Effective stop temperature")
    edit(curve,
        '  const xStart = tempToX(effectiveStart);\n',
        '  const xStart = tempToX(effectiveStart);\n  const xStop = tempToX(effectiveStop);\n',
        "SVG handle x position")
    edit(curve,
        '  const displayStart = Math.round(effectiveStart);\n',
        '  const displayStart = Math.round(effectiveStart);\n  const displayStop = Math.round(effectiveStop);\n',
        "Stop badge displays real threshold")
    edit(curve,
        '''const startDragPump = (e: React.MouseEvent, type: 'start' | 'turbo') => {''',
        '''const startDragPump = (e: React.MouseEvent, type: 'stop' | 'start' | 'turbo') => {''',
        "Extend interactive handle types")
    edit(curve,
        '''    const initialHandleSvgX = tempToX(type === 'start' ? effectiveStart : effectiveTurbo);''',
        '''    const initialHandleSvgX = tempToX(type === 'stop' ? effectiveStop : type === 'start' ? effectiveStart : effectiveTurbo);''',
        "No jumping during stop slider drag")
    edit(curve,
        '    let curIntStart = localPumpStart;\n',
        '    let curIntStart = localPumpStart;\n    let curIntStop = localPumpStop;\n',
        "Track committed stop temperature")
    edit(curve,
        '''          if (type === 'start') {
            const clamped = Math.max(35, Math.min(localPumpTurbo - 5, floatTemp));''',
        '''          if (type === 'stop') {
            const clamped = Math.max(30, Math.min(localPumpStart - 3, floatTemp));
            curIntStop = Math.round(clamped);
            setDraggingFloatStop(clamped);
            setLocalPumpStop(curIntStop);
          } else if (type === 'start') {
            const clamped = Math.max(Math.max(35, localPumpStop + 3), Math.min(localPumpTurbo - 5, floatTemp));''',
        "Enforce stop < start < turbo while dragging")
    edit(curve,
        '      setDraggingFloatStart(null);\n',
        '      setDraggingFloatStart(null);\n      setDraggingFloatStop(null);\n',
        "Finish drag without stale stop input")
    edit(curve,
        '''      const finalStart = type === 'start' ? curIntStart : localPumpStart;''',
        '''      const finalStart = type === 'start' ? curIntStart : localPumpStart;
      const finalStop = type === 'stop' ? curIntStop : localPumpStop;''',
        "Calculate stop value on mouseup")
    edit(curve,
        '''      setLocalPumpStart(finalStart);
      setLocalPumpTurbo(finalTurbo);
      onPumpThresholdsChange?.(finalStart, finalTurbo, true);''',
        '''      setLocalPumpStart(finalStart);
      setLocalPumpStop(finalStop);
      setLocalPumpTurbo(finalTurbo);
      onPumpThresholdsChange?.(finalStop, finalStart, finalTurbo, true);''',
        "Persist all 3 draggable temperatures at once")
    edit(curve,
        '水泵工况 (双杆可拖拽: 启泵/狂暴)',
        '水泵工况 (拖动温度线：停泵 / 启泵 / 狂暴)',
        "Label three independent temperature handles")
    edit(curve,
        '''          {xStart - startX > 65 && (
            <text x={startX + 8} y="42" fill="#34d399" fontSize="9" fontWeight="700" opacity="0.7">
              低温停转区 (&lt;{displayStart}°C)''',
        '''          {xStart - startX > 65 && (
            <text x={startX + 8} y="42" fill="#34d399" fontSize="9" fontWeight="700" opacity="0.7">
              低温停转区 (≤{gpuOnlyModel ? displayStop : displayStart - 5}°C)''',
        "Correctly label actual shutdown threshold")
    edit(curve,
        '''          {/* 启泵阈值手柄杆 (可左右拖拽) */}''',
        '''          {gpuOnlyModel && (
            <g style={{ cursor: 'ew-resize', userSelect: 'none' }}
              onMouseDown={(e) => startDragPump(e, 'stop')}>
              <line x1={xStop} y1="15" x2={xStop} y2="120" stroke="#a78bfa"
                strokeWidth={activeDragPump === 'stop' ? 2.5 : 1.8} strokeDasharray="3,3" />
              <g transform={'translate(' + xStop + ', 31)'}>
                <rect x="-29" y="0" width="58" height="14" rx="3" fill="#7c3aed" />
                <text x="0" y="10" fill="#ffffff" fontSize="8.5" fontWeight="700" textAnchor="middle">
                  {displayStop}° 停泵
                </text>
              </g>
              <g transform={'translate(' + xStop + ', 75)'}>
                <rect x="-5" y="-8" width="10" height="16" rx="3"
                  fill="#8b5cf6" stroke="#fff" strokeWidth="1.2" />
              </g>
              <rect x={xStop - 11} y="15" width="22" height="105" fill="transparent" />
            </g>
          )}

          {/* 启泵阈值手柄杆 (可左右拖拽) */}''',
        "Create visible draggable purple stop slider (third handle)")
    edit(curve,
        '''          <text x={xStart} y="134" fill="#34d399" fontSize="9" fontWeight="800" textAnchor="middle">''',
        '''          {gpuOnlyModel && (
            <text x={xStop} y="116" fill="#a78bfa" fontSize="9" fontWeight="800" textAnchor="middle">
              {displayStop}°停泵
            </text>
          )}
          <text x={xStart} y="134" fill="#34d399" fontSize="9" fontWeight="800" textAnchor="middle">''',
        "Display stop threshold on chart bottom without hiding start")

    # The preview used to show curve interpolation instead of actual pump commands.
    edit(presets,
        '  smartPhase?: string;\n  smartWaitSecs?: number;\n',
        '  smartPhase?: string;\n  smartWaitSecs?: number;\n  actualPumpTier?: number;\n  actualFanDuty?: number;\n',
        "Use authoritative pump status for smart card")
    edit(presets,
        '  smartPhase,\n  smartWaitSecs,\n',
        '  smartPhase,\n  smartWaitSecs,\n  actualPumpTier,\n  actualFanDuty,\n',
        "Read actual commanded tier and duty")
    edit(ui,
        '          smartWaitSecs={coolerData.smart_wait_secs}\n',
        '          smartWaitSecs={coolerData.smart_wait_secs}\n'
        '          actualPumpTier={coolerData.pump_tier}\n'
        '          actualFanDuty={coolerData.fan_duty}\n',
        "Pass command state from backend to preset card")
    edit(presets,
        '随动: {liveMaxTemp}°C → 风扇 {liveInterpolated.duty}% | 水泵 {',
        "控制指令: {liveMaxTemp}°C → 风扇 {gpuOnlyModel ? (actualFanDuty ?? 0) : liveInterpolated.duty}% | 水泵 {",
        "Stop showing prediction as physical motor state")
    edit(presets,
        '''liveInterpolated.volt >= 11 || liveInterpolated.volt === 3''',
        '''(gpuOnlyModel ? actualPumpTier === 3 : liveInterpolated.volt >= 11 || liveInterpolated.volt === 3)''',
        "Use actual turbo command in new preview")
    edit(presets,
        '''liveInterpolated.volt === 0''',
        '''(gpuOnlyModel ? actualPumpTier === 0 : liveInterpolated.volt === 0)''',
        "Use actual stop command in new preview")

    print("r5 complete; no installed hardware was changed.")

if __name__=="__main__":
    main()
