#![allow(unexpected_cfgs)]
//! GM6IX8X adaptive cooler supervisor: separate thermal histories -> weighted heat
//! pressure -> hysteretic pump state. High individual temperatures are *safety* trips,
//! never the ordinary pump control signal.
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};
#[cfg(not(r7_standalone_test))]
use super::ble_cooler::CoolerPumpTier;
#[cfg(r7_standalone_test)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum CoolerPumpTier { Stop, Silent, Standard, Turbo }

#[derive(Clone, Copy, Debug)]
pub struct Thresholds {
    gpu_start: u8,
    gpu_stop: u8,
    gpu_turbo: u8,
}
impl Thresholds {
    pub fn safe(start: u8, stop: u8, turbo: u8) -> Self {
        let gpu_start = start.clamp(35, 80);
        Self {
            gpu_start,
            gpu_stop: stop.clamp(30, gpu_start.saturating_sub(3)),
            gpu_turbo: turbo.clamp(gpu_start.saturating_add(5), 98),
        }
    }
    fn cpu_start(self) -> u8 { self.gpu_start.saturating_add(5).min(95) }
    fn cpu_stop(self) -> u8 { self.gpu_stop.saturating_add(3).min(95) }
    fn cpu_turbo(self) -> u8 { self.gpu_turbo.saturating_add(2).min(98) }
}

#[cfg(not(r7_standalone_test))]
pub fn is_active_machine() -> bool {
    static ACTIVE: OnceLock<bool> = OnceLock::new();
    *ACTIVE.get_or_init(|| {
        crate::system::model_engine::get_device_full_name()
            .to_ascii_uppercase().contains("GM6IX8X")
    })
}

#[cfg(not(r7_standalone_test))]
fn current_sensors() -> (Option<u8>, Option<u8>) {
    let ct = crate::system::cpu_monitor::get_global_cpu_monitor().get_temp();
    let cpu = if (10..=110).contains(&ct) { Some(ct as u8) } else { None };
    let g = crate::driver::gpu_bridge::get_global_gpu();
    let guard = g.lock();
    let gpu = if guard.get_gpu_count() > 0 {
        let value = guard.get_temp(0);
        if (10..=110).contains(&value) { Some(value as u8) } else { None }
    } else { None };
    (cpu, gpu)
}

#[derive(Debug)]
struct Policy {
    tier: CoolerPumpTier,
    tier_since: Instant,
    last_eval: Instant,
    cpu_ema: Option<f32>,
    gpu_ema: Option<f32>,
    heat_debt: f32,
    fan: u8,
    start_since: Option<Instant>,
    stop_since: Option<Instant>,
    turbo_since: Option<Instant>,
    turbo_exit_since: Option<Instant>,
}
impl Policy {
    fn new(now: Instant) -> Self {
        Self {
            tier: CoolerPumpTier::Standard,
            tier_since: now,
            last_eval: now,
            cpu_ema: None, gpu_ema: None,
            heat_debt: 0.0, fan: 45,
            start_since: None, stop_since: None,
            turbo_since: None, turbo_exit_since: None,
        }
    }
    fn smoother(old: Option<f32>, sample: Option<u8>, dt: f32, tau: f32) -> Option<f32> {
        sample.map(|v| {
            let x = v as f32;
            old.map(|prev| prev + (x - prev) * (1.0 - (-dt / tau).exp())).unwrap_or(x)
        })
    }
    fn sustained(slot: &mut Option<Instant>, now: Instant, condition: bool, hold: Duration) -> bool {
        if !condition { *slot = None; return false; }
        match *slot {
            None => { *slot = Some(now); false }
            Some(started) => now.saturating_duration_since(started) >= hold,
        }
    }
    fn change_tier(&mut self, tier: CoolerPumpTier, now: Instant) {
        if tier == self.tier { return; }
        self.tier = tier;
        self.tier_since = now;
        self.start_since = None;
        self.stop_since = None;
        self.turbo_since = None;
        self.turbo_exit_since = None;
    }
    fn update(&mut self, now: Instant, cpu: Option<u8>, gpu: Option<u8>, t: Thresholds) -> (CoolerPumpTier, u8) {
        let dt = now.saturating_duration_since(self.last_eval).as_secs_f32().clamp(0.0, 10.0);
        self.last_eval = now;

        // Two different thermal time constants: short CPU boost spikes are discounted,
        // sustained GPU heat is accumulated without treating degrees as equivalent load.
        self.cpu_ema = Self::smoother(self.cpu_ema, cpu, dt, 9.0);
        self.gpu_ema = Self::smoother(self.gpu_ema, gpu, dt, 13.0);

        // Safety overrides are intentionally independent of smoothed control.
        let emergency = cpu.is_some_and(|v| v >= 98) || gpu.is_some_and(|v| v >= 95);
        let missing = self.cpu_ema.is_none() || self.gpu_ema.is_none();

        let cpu_pressure = self.cpu_ema.map(|temp| {
            ((temp - t.cpu_stop() as f32)
                / (t.cpu_turbo() as f32 - t.cpu_stop() as f32).max(1.0)).clamp(0.0, 1.3)
        }).unwrap_or(0.0);
        let gpu_pressure = self.gpu_ema.map(|temp| {
            ((temp - t.gpu_stop as f32)
                / (t.gpu_turbo as f32 - t.gpu_stop as f32).max(1.0)).clamp(0.0, 1.3)
        }).unwrap_or(0.0);

        // Heat pressure is a fused and accumulated quantity, not max(cpu,gpu).
        // The CPU gets priority for the new CPU-cooled hardware variant; the
        // GPU contributes its own persistent load, and simultaneous load adds a bonus.
        let fused_pressure = (0.64 * cpu_pressure
            + 0.36 * gpu_pressure
            + 0.12 * cpu_pressure.min(gpu_pressure)).clamp(0.0, 1.45);
        let alpha = 1.0 - (-dt / 16.0).exp();
        self.heat_debt += (fused_pressure - self.heat_debt) * alpha;

        let start_condition = self.heat_debt >= 0.11
            || cpu.is_some_and(|v| v >= 82)
            || gpu.is_some_and(|v| v >= 78);
        let stop_condition = self.heat_debt <= 0.055
            && self.cpu_ema.is_some_and(|v| v <= t.cpu_stop() as f32)
            && self.gpu_ema.is_some_and(|v| v <= t.gpu_stop as f32);
        let turbo_condition = self.heat_debt >= 0.72
            || self.cpu_ema.is_some_and(|v| v >= t.cpu_turbo() as f32 - 2.0)
            || self.gpu_ema.is_some_and(|v| v >= t.gpu_turbo as f32 - 3.0);
        let turbo_exit = self.heat_debt <= 0.42
            && self.cpu_ema.is_some_and(|v| v < t.cpu_turbo() as f32 - 9.0)
            && self.gpu_ema.is_some_and(|v| v < t.gpu_turbo as f32 - 9.0);
        let start = Self::sustained(&mut self.start_since, now, start_condition, Duration::from_secs(5));
        let stop = Self::sustained(&mut self.stop_since, now, stop_condition, Duration::from_secs(25));
        let turbo = Self::sustained(&mut self.turbo_since, now, turbo_condition, Duration::from_secs(7));
        let exit = Self::sustained(&mut self.turbo_exit_since, now, turbo_exit, Duration::from_secs(15));
        let tier_time = now.saturating_duration_since(self.tier_since);

        if emergency {
            self.change_tier(CoolerPumpTier::Turbo, now);
        } else if missing {
            // Failed sensor is not zero heat. Keep circulation available.
            if self.tier != CoolerPumpTier::Turbo { self.change_tier(CoolerPumpTier::Standard, now); }
        } else {
            match self.tier {
                CoolerPumpTier::Stop => {
                    if turbo { self.change_tier(CoolerPumpTier::Turbo, now); }
                    else if start && tier_time >= Duration::from_secs(15) {
                        self.change_tier(CoolerPumpTier::Standard, now);
                    }
                }
                CoolerPumpTier::Turbo => {
                    if exit { self.change_tier(CoolerPumpTier::Standard, now); }
                }
                CoolerPumpTier::Standard | CoolerPumpTier::Silent => {
                    if turbo { self.change_tier(CoolerPumpTier::Turbo, now); }
                    else if stop && tier_time >= Duration::from_secs(60) {
                        self.change_tier(CoolerPumpTier::Stop, now);
                    }
                }
            }
        }

        let target_fan = match self.tier {
            CoolerPumpTier::Stop => 0,
            CoolerPumpTier::Turbo if emergency => 100,
            CoolerPumpTier::Turbo => 90,
            _ if missing => 65,
            _ => (34.0 + 58.0 * self.heat_debt.sqrt()).round().clamp(34.0, 95.0) as u8,
        };

        // Ramp is expressed per second rather than per polling tick.
        if emergency || self.tier == CoolerPumpTier::Stop {
            self.fan = target_fan;
        } else {
            let up = (6.0 * dt).ceil().max(2.0) as u8;
            let down = (2.5 * dt).ceil().max(1.0) as u8;
            self.fan = if target_fan > self.fan {
                target_fan.min(self.fan.saturating_add(up))
            } else {
                target_fan.max(self.fan.saturating_sub(down))
            };
        }
        (self.tier, self.fan)
    }
}

#[cfg(not(r7_standalone_test))]
pub fn evaluate_live(start: u8, stop: u8, turbo: u8) -> (CoolerPumpTier, u8) {
    static STATE: OnceLock<Mutex<Policy>> = OnceLock::new();
    let now = Instant::now();
    let state = STATE.get_or_init(|| Mutex::new(Policy::new(now)));
    let mut policy = state.lock().unwrap_or_else(|e| e.into_inner());
    let (cpu, gpu) = current_sensors();
    policy.update(now, cpu, gpu, Thresholds::safe(start, stop, turbo))
}

#[cfg(not(r7_standalone_test))]
pub fn reset_live() {
    static RESET_NOTE: OnceLock<()> = OnceLock::new();
    // The supervisor is process-scoped; explicit reinitialization can be added
    // after hardware sleep/wake handshake, once the device protocol is verified.
    let _ = RESET_NOTE.get_or_init(|| ());
}

#[cfg(test)]
mod dual_loop_tests {
    use super::*;
    fn at(t: Instant, secs: u64) -> Instant { t + Duration::from_secs(secs) }
    fn step(p: &mut Policy, t: Instant, cpu: Option<u8>, gpu: Option<u8>) -> (CoolerPumpTier, u8) {
        p.update(t, cpu, gpu, Thresholds::safe(55, 47, 90))
    }
    fn idle_to_stop(p: &mut Policy, t: Instant) {
        for n in 0..85 { step(p, at(t,n), Some(41),Some(39)); }
        assert_eq!(p.tier,CoolerPumpTier::Stop);
    }
    #[test]
    fn idle_stops_and_uses_zero_fan() {
        let t=Instant::now(); let mut p=Policy::new(t);
        idle_to_stop(&mut p,t);
        assert_eq!(p.fan,0);
    }
    #[test]
    fn short_cpu_spike_is_ignored_without_emergency() {
        let t=Instant::now(); let mut p=Policy::new(t);
        idle_to_stop(&mut p,t);
        assert_eq!(step(&mut p,at(t,86),Some(84),Some(39)).0,CoolerPumpTier::Stop);
        assert_eq!(step(&mut p,at(t,87),Some(41),Some(39)).0,CoolerPumpTier::Stop);
    }
    #[test]
    fn sustained_cpu_heat_starts_pump() {
        let t=Instant::now(); let mut p=Policy::new(t);
        idle_to_stop(&mut p,t);
        for n in 86..126 { step(&mut p, at(t,n),Some(77),Some(39)); }
        assert_eq!(p.tier,CoolerPumpTier::Standard);
    }
    #[test]
    fn sustained_gpu_heat_starts_pump() {
        let t=Instant::now(); let mut p=Policy::new(t);
        idle_to_stop(&mut p,t);
        for n in 86..136 { step(&mut p,at(t,n),Some(41),Some(73)); }
        assert_eq!(p.tier,CoolerPumpTier::Standard);
    }
    #[test]
    fn combined_moderate_heat_builds_more_pressure_than_one_source() {
        let t=Instant::now(); let mut both=Policy::new(t); let mut cpu_only=Policy::new(t);
        for n in 0..80 {
            step(&mut both,at(t,n),Some(75),Some(69));
            step(&mut cpu_only,at(t,n),Some(75),Some(39));
        }
        assert!(both.heat_debt>cpu_only.heat_debt);
        assert!(both.fan>=cpu_only.fan);
    }
    #[test]
    fn sensor_loss_cannot_cause_stop() {
        let t=Instant::now(); let mut p=Policy::new(t);
        idle_to_stop(&mut p,t);
        let (tier,fan)=step(&mut p,at(t,90),Some(40),None);
        assert_eq!(tier,CoolerPumpTier::Standard);
        assert!(fan>0);
    }
    #[test]
    fn emergencies_bypass_smoothing() {
        let t=Instant::now(); let mut p=Policy::new(t);
        assert_eq!(step(&mut p,at(t,1),Some(98),Some(40)),(CoolerPumpTier::Turbo,100));
    }
    #[test]
    fn stop_requires_both_cooled_and_dwell() {
        let t=Instant::now(); let mut p=Policy::new(t);
        for n in 0..80 { step(&mut p,at(t,n),Some(75),Some(72)); }
        assert_eq!(p.tier,CoolerPumpTier::Standard);
        for n in 80..190 { step(&mut p,at(t,n),Some(41),Some(39)); }
        assert_eq!(p.tier,CoolerPumpTier::Stop);
    }
}
