//! GM6IX8X dual-source external cooler policy. No EC writes, no BLE protocol changes.
//! The platform-gated caller converts these decisions into existing OpenRevo pump tiers.
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use super::ble_cooler::CoolerPumpTier;

#[derive(Clone, Copy, Debug)]
pub struct Thresholds {
    pub gpu_start: u8,
    pub gpu_stop: u8,
    pub gpu_turbo: u8,
}
impl Thresholds {
    pub fn safe(start: u8, stop: u8, turbo: u8) -> Self {
        let start = start.clamp(35, 80);
        Self {
            gpu_start: start,
            gpu_stop: stop.clamp(30, start.saturating_sub(3)),
            gpu_turbo: turbo.clamp(start.saturating_add(5), 98),
        }
    }
    fn cpu_start(self) -> u8 { self.gpu_start.saturating_add(5).min(95) }
    fn cpu_stop(self) -> u8 { self.gpu_stop.saturating_add(3).min(95) }
    fn cpu_turbo(self) -> u8 { self.gpu_turbo.saturating_add(2).min(98) }
}

pub fn is_active_machine() -> bool {
    static ACTIVE: OnceLock<bool> = OnceLock::new();
    *ACTIVE.get_or_init(|| {
        crate::system::model_engine::get_device_full_name()
            .to_ascii_uppercase().contains("GM6IX8X")
    })
}

fn current_sensors() -> (Option<u8>, Option<u8>) {
    let ct = crate::system::cpu_monitor::get_global_cpu_monitor().get_temp();
    let cpu = if (10..=110).contains(&ct) { Some(ct as u8) } else { None };
    let g = crate::driver::gpu_bridge::get_global_gpu();
    let guard = g.lock();
    let gpu = if guard.get_gpu_count() > 0 {
        let gt = guard.get_temp(0);
        if (10..=110).contains(&gt) { Some(gt as u8) } else { None }
    } else { None };
    (cpu, gpu)
}

struct Policy {
    tier: CoolerPumpTier,
    since: Instant,
    startup: Instant,
    fan: u8,
    start_candidate: Option<Instant>,
    stop_candidate: Option<Instant>,
    turbo_candidate: Option<Instant>,
    turbo_exit_candidate: Option<Instant>,
}

impl Policy {
    fn new(now: Instant) -> Self {
        Self { tier: CoolerPumpTier::Standard, since: now, startup: now, fan: 45,
            start_candidate: None, stop_candidate: None,
            turbo_candidate: None, turbo_exit_candidate: None }
    }

    fn sustained(slot: &mut Option<Instant>, now: Instant, test: bool, required: Duration) -> bool {
        if !test { *slot = None; return false; }
        match *slot {
            None => { *slot = Some(now); false },
            Some(t) => now.saturating_duration_since(t) >= required,
        }
    }

    fn update(&mut self, now: Instant, cpu: Option<u8>, gpu: Option<u8>, t: Thresholds) -> (CoolerPumpTier, u8) {
        let urgent = cpu.is_some_and(|v| v >= 98) || gpu.is_some_and(|v| v >= 95);
        let incomplete = cpu.is_none() || gpu.is_none();
        let start = cpu.is_some_and(|v| v >= t.cpu_start()) || gpu.is_some_and(|v| v >= t.gpu_start);
        let stop = cpu.is_some_and(|v| v <= t.cpu_stop()) && gpu.is_some_and(|v| v <= t.gpu_stop);
        let turbo = cpu.is_some_and(|v| v >= t.cpu_turbo()) || gpu.is_some_and(|v| v >= t.gpu_turbo);
        let exit_turbo = cpu.is_some_and(|v| v <= t.cpu_turbo().saturating_sub(7))
            && gpu.is_some_and(|v| v <= t.gpu_turbo.saturating_sub(7));

        let hot_enough = Self::sustained(&mut self.start_candidate, now, start, Duration::from_secs(3));
        let cool_enough = Self::sustained(&mut self.stop_candidate, now, stop, Duration::from_secs(25));
        let turbo_enough = Self::sustained(&mut self.turbo_candidate, now, turbo, Duration::from_secs(3));
        let turbo_receded = Self::sustained(&mut self.turbo_exit_candidate, now, exit_turbo, Duration::from_secs(12));
        let elapsed = now.saturating_duration_since(self.since);
        let next = if urgent { CoolerPumpTier::Turbo }
            else if incomplete {
                if self.tier == CoolerPumpTier::Turbo { CoolerPumpTier::Turbo } else { CoolerPumpTier::Standard }
            } else {
                match self.tier {
                    CoolerPumpTier::Stop => {
                        if turbo_enough { CoolerPumpTier::Turbo }
                        else if hot_enough && elapsed >= Duration::from_secs(15) { CoolerPumpTier::Standard }
                        else { CoolerPumpTier::Stop }
                    }
                    CoolerPumpTier::Turbo => {
                        if turbo_receded { CoolerPumpTier::Standard } else { CoolerPumpTier::Turbo }
                    }
                    CoolerPumpTier::Silent | CoolerPumpTier::Standard => {
                        if turbo_enough { CoolerPumpTier::Turbo }
                        else if cool_enough && elapsed >= Duration::from_secs(45)
                             && now.saturating_duration_since(self.startup) >= Duration::from_secs(45) {
                            CoolerPumpTier::Stop
                        } else { CoolerPumpTier::Standard }
                    }
                }
            };
        if next != self.tier {
            self.tier = next;
            self.since = now;
            self.start_candidate = None;
            self.stop_candidate = None;
            self.turbo_candidate = None;
            self.turbo_exit_candidate = None;
        }
        let target_fan = match self.tier {
            CoolerPumpTier::Stop => 0,
            CoolerPumpTier::Turbo if urgent => 100,
            CoolerPumpTier::Turbo => 90,
            _ if incomplete => 65,
            _ => {
                let cpu_heat = cpu.map(|v| ((v as f32 - 55.0) / 40.0).clamp(0.0, 1.0)).unwrap_or(0.0);
                let gpu_heat = gpu.map(|v| ((v as f32 - 48.0) / 42.0).clamp(0.0, 1.0)).unwrap_or(0.0);
                (38.0 + 47.0 * cpu_heat.max(gpu_heat)).round() as u8
            }
        };
        self.fan = if urgent || self.tier == CoolerPumpTier::Stop { target_fan }
            else if target_fan > self.fan { target_fan.min(self.fan.saturating_add(12)) }
            else { target_fan.max(self.fan.saturating_sub(5)) };
        (self.tier, self.fan)
    }
}

pub fn evaluate_live(start: u8, stop: u8, turbo: u8) -> (CoolerPumpTier, u8) {
    static POLICY: OnceLock<Mutex<Policy>> = OnceLock::new();
    let now = Instant::now();
    let policy = POLICY.get_or_init(|| Mutex::new(Policy::new(now)));
    let mut state = policy.lock().unwrap_or_else(|e| e.into_inner());
    let (cpu, gpu) = current_sensors();
    state.update(now, cpu, gpu, Thresholds::safe(start, stop, turbo))
}

#[cfg(test)]
mod dual_loop_tests {
    use super::*;
    fn later(t: Instant, seconds: u64) -> Instant { t + Duration::from_secs(seconds) }
    fn eval(p: &mut Policy, t: Instant, cpu: Option<u8>, gpu: Option<u8>) -> (CoolerPumpTier, u8) {
        p.update(t, cpu, gpu, Thresholds::safe(55, 47, 90))
    }
    #[test]
    fn cpu_sustained_load_starts_after_cooldown() {
        let t = Instant::now(); let mut p = Policy::new(t);
        assert_eq!(eval(&mut p, later(t, 50), Some(42), Some(40)).0, CoolerPumpTier::Standard);
        assert_eq!(eval(&mut p, later(t, 80), Some(42), Some(40)).0, CoolerPumpTier::Stop);
        assert_eq!(eval(&mut p, later(t, 90), Some(70), Some(42)).0, CoolerPumpTier::Stop);
        assert_eq!(eval(&mut p, later(t, 94), Some(70), Some(42)).0, CoolerPumpTier::Standard);
    }
    #[test]
    fn cpu_one_second_spike_does_not_start_stopped_pump() {
        let t=Instant::now(); let mut p=Policy::new(t);
        eval(&mut p,later(t,50),Some(40),Some(39));
        eval(&mut p,later(t,80),Some(40),Some(39));
        assert_eq!(eval(&mut p,later(t,90),Some(82),Some(39)).0,CoolerPumpTier::Stop);
        assert_eq!(eval(&mut p,later(t,91),Some(41),Some(39)).0,CoolerPumpTier::Stop);
    }
    #[test]
    fn missing_sensor_fails_running_not_stop() {
        let t=Instant::now(); let mut p=Policy::new(t);
        let (tier,fan)=eval(&mut p,later(t,60),Some(42),None);
        assert_eq!(tier,CoolerPumpTier::Standard); assert!(fan>0);
    }
    #[test]
    fn sustained_turbo_and_urgent_override() {
        let t=Instant::now(); let mut p=Policy::new(t);
        assert_eq!(eval(&mut p,later(t,1),Some(93),Some(65)).0,CoolerPumpTier::Standard);
        assert_eq!(eval(&mut p,later(t,5),Some(93),Some(65)).0,CoolerPumpTier::Turbo);
        assert_eq!(eval(&mut p,later(t,8),Some(98),Some(40)),(CoolerPumpTier::Turbo,100));
    }
    #[test]
    fn stop_requires_both_cool_and_dwell() {
        let t=Instant::now(); let mut p=Policy::new(t);
        eval(&mut p,later(t,50),Some(46),Some(44));
        assert_eq!(eval(&mut p,later(t,80),Some(46),Some(48)).0,CoolerPumpTier::Standard);
        eval(&mut p,later(t,85),Some(46),Some(44));
        assert_eq!(eval(&mut p,later(t,111),Some(46),Some(44)).0,CoolerPumpTier::Stop);
    }
}
