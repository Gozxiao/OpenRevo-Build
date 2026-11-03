#!/usr/bin/env python3
"""R4: fix r3's overly long pump delays, expose state/reasons & model, fix misleading UI.

Runs after the existing r3 guarded patch and preserves all non-GM6PX8X behavior.
"""
from pathlib import Path
import sys

def replace_once(path, old, new, description):
    s=path.read_text(encoding="utf-8")
    n=s.count(old)
    if n != 1:
        raise SystemExit(f"{description}: expected exactly one match, found {n} in {path}")
    path.write_text(s.replace(old,new,1),encoding="utf-8",newline="\n")
    print("Patched:",description)

def main():
    root=Path(sys.argv[1]).resolve()
    cooler=root/"src-tauri/src/driver/ble_cooler.rs"
    types=root/"src/components/water_cooler/coolerTypes.ts"
    header=root/"src/components/water_cooler/CoolerHeaderTelemetry.tsx"
    presets=root/"src/components/water_cooler/CoolerPresetCards.tsx"
    for p in [cooler,types,header,presets]:
        if not p.is_file(): raise SystemExit(f"Missing: {p}")

    replace_once(cooler,
        'pub fn is_gm6px8x_gpu_only_cooler() -> bool {',
        '''fn cooler_bios_model_name() -> &'static str {
    static BIOS_MODEL: std::sync::OnceLock<String> = std::sync::OnceLock::new();
    BIOS_MODEL.get_or_init(crate::system::model_engine::get_device_full_name).as_str()
}

pub fn is_gm6px8x_gpu_only_cooler() -> bool {''',
        "Cache physical BIOS model name")

    replace_once(cooler,
        '        let bios_model = crate::system::model_engine::get_device_full_name();',
        '        let bios_model = cooler_bios_model_name();',
        "Use cached physical BIOS model for safety gate")

    current=cooler.read_text(encoding="utf-8")
    start=current.index("/// A stateful pump anti-cycling gate.")
    end=current.index("\npub fn calculate_strategy_params(",start)
    old=current[start:end]
    new=r'''/// GM6PX8X only: quick start, bounded shutdown delay, and 8 C hysteresis.
/// The 1 Hz BLE supervisor is the only writer; all timers use Instant.
const GM6_START_HOLD_SECS: u64 = 3;
const GM6_STOP_HOLD_SECS: u64 = 20;
const GM6_MIN_ON_SECS: u64 = 60;
const GM6_MIN_OFF_SECS: u64 = 40;
const GM6_STOP_HYSTERESIS_C: u8 = 8;
const GM6_FAST_START_C: u8 = 70;

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
            // First normal start is not blocked by a fake previous shutdown.
            off_since: None,
            warm_since: None,
            cool_since: None,
        }
    }
    fn transition(&mut self, next: CoolerPumpTier, now: Instant) -> CoolerPumpTier {
        if next != self.last_tier {
            if next == CoolerPumpTier::Stop {
                self.off_since = Some(now);
                self.on_since = None;
            } else if self.last_tier == CoolerPumpTier::Stop {
                self.on_since = Some(now);
                self.off_since = None;
            }
            self.last_tier = next;
            self.warm_since = None;
            self.cool_since = None;
        }
        next
    }
    fn elapsed(now: Instant, since: Option<Instant>) -> u64 {
        since.map(|s| now.saturating_duration_since(s).as_secs()).unwrap_or(0)
    }
    fn remain(now: Instant, since: Option<Instant>, target: u64) -> u32 {
        target.saturating_sub(Self::elapsed(now,since)) as u32
    }
    fn next(&mut self, current: CoolerPumpTier, gpu: Option<u8>, now: Instant,
        start: u8, turbo: u8) -> CoolerPumpTier {
        // Reset timers if an explicit manual mode or reconnect changed the tier.
        if current != self.last_tier { self.transition(current,now); }
        let t = match gpu {
            Some(value) => value,
            None => {
                // Unavailable sensor != cold GPU. Never authorize shutdown here.
                self.warm_since=None;
                self.cool_since=None;
                return current;
            }
        };
        if t >= turbo {
            return self.transition(CoolerPumpTier::Turbo,now);
        }

        if current == CoolerPumpTier::Stop {
            self.cool_since=None;
            // An actually hot GPU must not wait through off lockout.
            if t >= GM6_FAST_START_C {
                return self.transition(CoolerPumpTier::Standard,now);
            }
            if t < start { self.warm_since=None; return CoolerPumpTier::Stop; }
            if self.warm_since.is_none() {self.warm_since=Some(now);}
            let warm_enough=Self::elapsed(now,self.warm_since)>=GM6_START_HOLD_SECS;
            let off_enough=self.off_since
                .map(|x| now.saturating_duration_since(x).as_secs() >= GM6_MIN_OFF_SECS)
                .unwrap_or(true);
            if warm_enough && off_enough {
                self.transition(CoolerPumpTier::Standard,now)
            } else {CoolerPumpTier::Stop}
        } else {
            self.warm_since=None;
            if current==CoolerPumpTier::Turbo && t > turbo.saturating_sub(5) {
                self.cool_since=None;
                return CoolerPumpTier::Turbo;
            }
            // 55C start -> 47C stop: don't conflate 'under start' with 'cold'.
            if t <= start.saturating_sub(GM6_STOP_HYSTERESIS_C) {
                if self.cool_since.is_none() {self.cool_since=Some(now);}
                let cool_enough=Self::elapsed(now,self.cool_since)>=GM6_STOP_HOLD_SECS;
                let on_enough=self.on_since
                    .map(|x| now.saturating_duration_since(x).as_secs()>=GM6_MIN_ON_SECS)
                    .unwrap_or(false);
                if cool_enough && on_enough {
                    return self.transition(CoolerPumpTier::Stop,now);
                }
            } else {self.cool_since=None;}
            self.transition(CoolerPumpTier::Standard,now)
        }
    }
    /// User-visible explanation of what the controller is waiting for.
    fn describe(&self, tier: CoolerPumpTier, gpu: Option<u8>, now: Instant,
        start: u8, turbo: u8) -> (String,u32) {
        let Some(t) = gpu else {
            return ("GPU 温度不可用，保持当前水泵指令".to_string(),0);
        };
        if tier==CoolerPumpTier::Turbo {
            return ("GPU 高温强冷".to_string(),0);
        }
        if tier==CoolerPumpTier::Stop {
            if t < start {
                return (format!("低温待机（{}℃ 启泵）",start),0);
            }
            let warm=Self::remain(now,self.warm_since,GM6_START_HOLD_SECS);
            let lock=self.off_since
                .map(|_|Self::remain(now,self.off_since,GM6_MIN_OFF_SECS)).unwrap_or(0);
            if lock>0 {
                return ("短时停泵保护，等待重新启泵".to_string(),warm.max(lock));
            }
            return ("GPU 已达启动阈值，正在确认".to_string(),warm);
        }
        let stop=start.saturating_sub(GM6_STOP_HYSTERESIS_C);
        if t > stop {
            return (format!("水泵保持运行（≤{}℃ 才允许停泵）",stop),0);
        }
        let cool=Self::remain(now,self.cool_since,GM6_STOP_HOLD_SECS);
        let min_on=Self::remain(now,self.on_since,GM6_MIN_ON_SECS);
        ("低温确认，等待停泵".to_string(),cool.max(min_on))
    }
}

#[cfg(test)]
mod gpu_only_pump_guard_tests {
    use super::{CoolerPumpTier as Tier,Gm6px8xPumpGuard};
    use std::time::{Duration,Instant};
    #[test]
    fn idle_gpu_remains_off() {
        let at=Instant::now();
        let mut g=Gm6px8xPumpGuard::new(Tier::Stop,at);
        assert_eq!(g.next(Tier::Stop,Some(42),at,55,90),Tier::Stop);
        assert_eq!(g.next(Tier::Stop,Some(42),at+Duration::from_secs(300),55,90),Tier::Stop);
    }
    #[test]
    fn start_and_stop_are_timely_but_not_chattery() {
        let at=Instant::now();
        let mut g=Gm6px8xPumpGuard::new(Tier::Stop,at);
        assert_eq!(g.next(Tier::Stop,Some(55),at,55,90),Tier::Stop);
        assert_eq!(g.next(Tier::Stop,Some(56),at+Duration::from_secs(2),55,90),Tier::Stop);
        assert_eq!(g.next(Tier::Stop,Some(56),at+Duration::from_secs(3),55,90),Tier::Standard);
        assert_eq!(g.next(Tier::Standard,Some(46),at+Duration::from_secs(15),55,90),Tier::Standard);
        assert_eq!(g.next(Tier::Standard,Some(46),at+Duration::from_secs(40),55,90),Tier::Standard);
        assert_eq!(g.next(Tier::Standard,Some(46),at+Duration::from_secs(64),55,90),Tier::Stop);
        assert_eq!(g.next(Tier::Stop,Some(56),at+Duration::from_secs(65),55,90),Tier::Stop);
        assert_eq!(g.next(Tier::Stop,Some(56),at+Duration::from_secs(106),55,90),Tier::Standard);
    }
    #[test]
    fn immediate_high_heat_and_sensor_loss_guard() {
        let at=Instant::now();
        let mut g=Gm6px8xPumpGuard::new(Tier::Stop,at);
        assert_eq!(g.next(Tier::Stop,Some(72),at,55,90),Tier::Standard);
        assert_eq!(g.next(Tier::Standard,Some(95),at+Duration::from_secs(1),55,90),Tier::Turbo);
        assert_eq!(g.next(Tier::Turbo,None,at+Duration::from_secs(400),55,90),Tier::Turbo);
    }
    #[test]
    fn temperature_above_stop_threshold_does_not_shutdown() {
        let at=Instant::now();
        let mut g=Gm6px8xPumpGuard::new(Tier::Standard,at);
        assert_eq!(g.next(Tier::Standard,Some(49),at+Duration::from_secs(500),55,90),Tier::Standard);
        let (text,remaining)=g.describe(Tier::Standard,Some(49),at+Duration::from_secs(500),55,90);
        assert!(text.contains("47"));
        assert_eq!(remaining,0);
    }
}'''
    replace_once(cooler,old,new,"Shorter GM6PX8X anti-cycling gate and actual Rust tests")

    replace_once(cooler,
        '''    pub pump_turbo_temp: AtomicU8, // 狂暴阈值（默认 90°C）
    // Safety protection''',
        '''    pub pump_turbo_temp: AtomicU8, // 狂暴阈值（默认 90°C）
    pub smart_phase: Arc<parking_lot::RwLock<String>>,
    pub smart_wait_secs: AtomicU32,
    // Safety protection''',
        "Controller state for smart reasoning")
    replace_once(cooler,
        '''                pump_turbo_temp: AtomicU8::new(90),
                safety_tripped: AtomicBool::new(false),''',
        '''                pump_turbo_temp: AtomicU8::new(90),
                smart_phase: Arc::new(parking_lot::RwLock::new("正在初始化".to_string())),
                smart_wait_secs: AtomicU32::new(0),
                safety_tripped: AtomicBool::new(false),''',
        "Initialize UI reasoning state")
    replace_once(cooler,
        '''    pub gpu_only_model: bool,
}

pub struct BleCoolerController {''',
        '''    pub gpu_only_model: bool,
    pub bios_model_name: String,
    pub smart_phase: String,
    pub smart_wait_secs: u32,
}

pub struct BleCoolerController {''',
        "Expose BIOS model and pump reasoning telemetry")
    replace_once(cooler,
        '''            gpu_only_model: is_gm6px8x_gpu_only_cooler(),
        }''',
        '''            gpu_only_model: is_gm6px8x_gpu_only_cooler(),
            bios_model_name: cooler_bios_model_name().to_string(),
            smart_phase: self.state.smart_phase.read().clone(),
            smart_wait_secs: self.state.smart_wait_secs.load(Ordering::SeqCst),
        }''',
        "Send BIOS model and countdown in cooler status API")
    replace_once(cooler,
        '''                let next_tier = if gm6 {
                    gm6_pump_guard.next(cur_tier, get_valid_gpu_temp(), Instant::now(), start_temp, turbo_temp)
                } else {
                    calculate_pump_tier_with_hysteresis(current_temp, cur_tier, start_temp, turbo_temp)
                };''',
        '''                let gpu_temp = if gm6 { get_valid_gpu_temp() } else { None };
                let now = Instant::now();
                let next_tier = if gm6 {
                    gm6_pump_guard.next(cur_tier, gpu_temp, now, start_temp, turbo_temp)
                } else {
                    calculate_pump_tier_with_hysteresis(current_temp, cur_tier, start_temp, turbo_temp)
                };
                if gm6 {
                    let (phase,remaining) = gm6_pump_guard.describe(next_tier,gpu_temp,now,start_temp,turbo_temp);
                    *self.state.smart_phase.write()=phase;
                    self.state.smart_wait_secs.store(remaining, Ordering::SeqCst);
                }''',
        "Update authoritative pump control phase with countdown")

    replace_once(types,
        '''  gpu_only_model?: boolean;''',
        '''  gpu_only_model?: boolean;
  bios_model_name?: string;
  smart_phase?: string;
  smart_wait_secs?: number;''',
        "Read backend model and phase in React")

    replace_once(header,
        '''}) => {
  return (
    <>
      {/* 1. 顶部连接状态与操作按钮组 */}''',
        '''}) => {
  const pumpCommandedOff = coolerData.pump_tier === 0 || coolerData.pump_voltage === 0;
  return (
    <>
      {/* 1. 顶部连接状态与操作按钮组 */}''',
        "Derive commanded pump status for honest flow indicator")

    replace_once(header,
        '''          )}
        </div>

        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>''',
        '''          )}
          <span
            title={'BIOS 原始型号：' + (coolerData.bios_model_name || '未识别') + '；' + (coolerData.gpu_only_model ? '已启用 GPU 独立水冷策略' : '采用原版联合温控策略')}
            style={{
              fontSize: '9px', fontWeight: 600, color: 'var(--status-info)',
              border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-xs)',
              padding: '3px 7px', maxWidth: '208px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'
            }}
          >
            {coolerData.gpu_only_model ? '机型：旷世16 Super (GM6PX8X)' : '机型：' + (coolerData.bios_model_name || '未识别')}
          </span>
        </div>

        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>''',
        "Display real BIOS-gated model result immediately after MAC badge")

    replace_once(header,
        '''              color: coolerData.connected
                ? (coolerData.is_flow_ok ? 'var(--status-ok)' : 'var(--status-warn)')
                : 'var(--text-muted)',''',
        '''              color: coolerData.connected
                ? (pumpCommandedOff ? 'var(--text-muted)' : coolerData.is_flow_ok ? 'var(--status-ok)' : 'var(--status-warn)')
                : 'var(--text-muted)',''',
        "Prevent green flow status with stop command")

    replace_once(header,
        '''            {coolerData.connected
              ? (coolerData.is_flow_ok || coolerData.meter_state === 2 || coolerData.meter_state === 1 ? '正常 (Flowing)' : coolerData.meter_state === 3 ? '微流/建立中' : '无流量')
              : '--'}''',
        '''            {coolerData.connected
              ? (pumpCommandedOff ? '停泵指令（流量未校验）' : coolerData.is_flow_ok || coolerData.meter_state === 2 || coolerData.meter_state === 1 ? '水流正常 (Flowing)' : coolerData.meter_state === 3 ? '微流/建立中' : '未检测到水流')
              : '--'}''',
        "Do not claim flowing when pump is commanded off")

    replace_once(presets,
        '''  gpuOnlyModel?: boolean;
  liveMaxTemp: number;''',
        '''  gpuOnlyModel?: boolean;
  smartPhase?: string;
  smartWaitSecs?: number;
  liveMaxTemp: number;''',
        "Add status explanation props to preset UI")
    replace_once(presets,
        '''  gpuOnlyModel,
  liveMaxTemp,''',
        '''  gpuOnlyModel,
  smartPhase,
  smartWaitSecs,
  liveMaxTemp,''',
        "Read status explanation props")
    replace_once(presets,
        '''          <div className="cooler-strat-sub" style={{ fontSize: '9px', fontWeight: 700, color: 'var(--status-info)', display: 'inline-flex', alignItems: 'center', gap: '3px' }}>''',
        '''          {gpuOnlyModel && strategy === 'smart' && (
            <div style={{ fontSize: '9px', color: 'var(--status-info)', lineHeight: 1.4 }}>
              当前判断：{smartPhase || '正在初始化'}{smartWaitSecs ? '（约剩 ' + smartWaitSecs + ' 秒）' : ''}
            </div>
          )}
          <div className="cooler-strat-sub" style={{ fontSize: '9px', fontWeight: 700, color: 'var(--status-info)', display: 'inline-flex', alignItems: 'center', gap: '3px' }}>''',
        "Show pump control decision instead of leaving delays invisible")

    ui=root/"src/components/WaterCoolerView.tsx"
    replace_once(ui,
        '''          gpuOnlyModel={coolerData.gpu_only_model}
          strategy={coolerData.strategy}''',
        '''          gpuOnlyModel={coolerData.gpu_only_model}
          smartPhase={coolerData.smart_phase}
          smartWaitSecs={coolerData.smart_wait_secs}
          strategy={coolerData.strategy}''',
        "Wire backend pump phase to visible UI")
    print("R4 model, timing, and status overlay applied")

if __name__=="__main__":
    main()
