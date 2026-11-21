#!/usr/bin/env python3
"""r10: restore the GPU Dynamic Boost contract automatically during startup.

Problem being fixed
-------------------
On the GM6IX8X (RTX 4080 Laptop) the GPU power ceiling stays at the platform default
(~160W) after a normal boot, and only returns to the profile's configured ceiling
(150W base + 25W Dynamic Boost = 175W) after the user manually creates or re-selects a
custom profile in the tuning page.

Root cause found in upstream b7d2b52
------------------------------------
1. `query_nvidia_power_limits_static()` never blocks. On a cold cache it spawns an async
   `nvidia-smi` probe and immediately returns `None`, so `probe_gpu_tuning_capabilities()`
   reports `is_pending = true` during early startup, with `max_db_watts = 0` and
   `max_total_tgp = 0`. `apply_ec_hardware_mode()` derives the Dynamic Boost wattage from
   those values (`0.clamp(5, 35) == 5`), i.e. the boot-time mode application writes a
   wrong Dynamic Boost value.
2. `UnifiedPowerActuator::global()` latches the GPU architecture in a `OnceLock` on first
   use. If that first use happens while the probe is still pending, the latched
   architecture (WideCtgp instead of FullPower) is wrong for the rest of the session.

Fix strategy
------------
Add one deferred task, started from the existing startup restore thread, that:
  * only runs for the Custom (beacon/tuning) power mode, on DC barrel power, when the
    active custom profile actually enables Dynamic Boost, and when no declarative
    manifest owns the hardware;
  * waits for the capability probe to become ready and retries a bounded number of times;
  * never touches `UnifiedPowerActuator` (and therefore never depends on the possibly
    stale `OnceLock` architecture); it calls the stateless, already-proven
    `wmi_ec::heal_gpu_power_contract()` which re-probes the GPU on every call;
  * derives the target Dynamic Boost wattage from the live capability probe clamped by the
    user's own profile, so nothing is hardcoded to 175W;
  * is idempotent: it reads the four contract registers first and skips the write when
    they already match;
  * verifies by reading the EC registers back, and stops early instead of hammering the
    EC when the hardware does not accept the values.

Untouched on purpose: CPU power limits, XTU, GPU core/memory clock offsets, fan curves,
water cooler pump policy, other power modes, and the EC write implementation itself.
"""
import sys
from pathlib import Path

CALL_ANCHOR = """        if effective_power_mode == 3 || effective_power_mode == 4 {
            let _ = crate::system::actuator::UnifiedPowerActuator::global().unlock_factory_full_release();
        }"""

CALL_PATCHED = CALL_ANCHOR + """
        // R10: re-assert the Custom-mode GPU Dynamic Boost contract once the VBIOS power
        // limit probe is ready. See fix_startup_gpu_contract.py for the full rationale.
        if effective_power_mode == 4 {
            spawn_startup_gpu_contract_restore();
        }"""

FUNCS_ANCHOR = """/// Spawns the startup hardware state restoration thread (power mode, limits, fan boost, AC recovery, display, lighting).
pub fn spawn_hardware_state_restore(ec_for_restore: crate::driver::ec_bridge::SharedEcBridge) {"""

FUNCS_BLOCK = r'''
/// R10 - Deferred, verified restoration of the GPU Dynamic Boost contract during startup.
///
/// Why this exists (verified against upstream b7d2b52):
/// * `query_nvidia_power_limits_static()` never blocks: on a cold cache it spawns an async
///   `nvidia-smi` probe and returns `None`, so `probe_gpu_tuning_capabilities()` reports
///   `is_pending = true` during early startup. Writing EC power registers in that window
///   derives the Dynamic Boost wattage from a 0W capability, i.e. writes a wrong value.
/// * `UnifiedPowerActuator::global()` latches the GPU architecture through a `OnceLock` on
///   first use, so an early pending probe can poison the architecture for the whole session.
/// Therefore this task never goes through the actuator and always calls the stateless
/// `heal_gpu_power_contract()`, which re-probes the GPU on every invocation.
fn spawn_startup_gpu_contract_restore() {
    std::thread::spawn(move || {
        let cfg = crate::system::config::load_config();
        let profile = cfg.custom_profile.clone();

        if !(profile.gpu_db_enabled || profile.gpu_super_perf) {
            crate::log_info!(
                "GPU_CONTRACT",
                "startup restore skipped: Dynamic Boost disabled in active custom profile"
            );
            return;
        }
        if !crate::commands::hardware_cmd::is_dc_round_plugged_in() {
            crate::log_info!("GPU_CONTRACT", "startup restore skipped: not on DC barrel power");
            return;
        }
        if crate::hal::declarative::load_matched_manifest().is_some() {
            crate::log_info!(
                "GPU_CONTRACT",
                "startup restore skipped: declarative manifest owns hardware power"
            );
            return;
        }

        let mut last_seen: Option<(u8, u8, u8, u8)> = None;

        for attempt in 1..=6u32 {
            std::thread::sleep(std::time::Duration::from_millis(if attempt == 1 {
                4000
            } else {
                2500
            }));

            let caps = crate::driver::gpu_bridge::probe_gpu_tuning_capabilities();
            if caps.is_pending
                || !caps.supports_gpu_tuning
                || caps.max_db_watts == 0
                || caps.max_total_tgp == 0
            {
                crate::log_info!(
                    "GPU_CONTRACT",
                    "attempt {}: GPU capabilities still pending (db={}W total={}W), waiting",
                    attempt,
                    caps.max_db_watts,
                    caps.max_total_tgp
                );
                continue;
            }

            let max_db_cap = caps.max_db_watts.clamp(5, 35) as u8;
            let target_db = if profile.gpu_super_perf {
                max_db_cap
            } else {
                profile.gpu_db_watts.clamp(5, max_db_cap)
            };
            let expected_total = caps.base_tgp_max_watts as u16 + target_db as u16;
            let expected = (0x07u8, 0x00u8, 0xFFu8, target_db);

            let seen = match read_gpu_contract_registers() {
                Some(v) => v,
                None => {
                    crate::log_warn!(
                        "GPU_CONTRACT",
                        "attempt {}: EC transport unavailable, retrying",
                        attempt
                    );
                    continue;
                }
            };

            if seen == expected {
                crate::log_info!(
                    "GPU_CONTRACT",
                    "attempt {}: contract already correct [DB={}W, expected total {}W], no write performed",
                    attempt,
                    target_db,
                    expected_total
                );
                return;
            }
            if last_seen == Some(seen) {
                crate::log_warn!(
                    "GPU_CONTRACT",
                    "readback unchanged after previous write: observed {:?}, expected {:?}; stopping to avoid repeated EC writes",
                    seen,
                    expected
                );
                return;
            }
            last_seen = Some(seen);

            let heal_ok = crate::driver::wmi_ec::heal_gpu_power_contract(
                profile.gpu_super_perf,
                Some(target_db),
            );
            std::thread::sleep(std::time::Duration::from_millis(700));

            match read_gpu_contract_registers() {
                Some(after) if after == expected => {
                    crate::log_info!(
                        "GPU_CONTRACT",
                        "startup contract restored on attempt {}: before={:?} after={:?} DB={}W expected_total={}W (heal_ok={})",
                        attempt,
                        seen,
                        after,
                        target_db,
                        expected_total,
                        heal_ok
                    );
                    return;
                }
                Some(after) => {
                    crate::log_warn!(
                        "GPU_CONTRACT",
                        "attempt {}: readback mismatch after write, before={:?} after={:?} expected={:?} (heal_ok={})",
                        attempt,
                        seen,
                        after,
                        expected,
                        heal_ok
                    );
                    last_seen = Some(after);
                }
                None => {
                    crate::log_warn!(
                        "GPU_CONTRACT",
                        "attempt {}: readback unavailable after write",
                        attempt
                    );
                }
            }
        }

        crate::log_warn!("GPU_CONTRACT", "startup contract restore gave up after 6 attempts");
    });
}

/// Read the EC registers that form the GPU Dynamic Boost contract.
/// Returns `None` when the EC transport is not available yet.
fn read_gpu_contract_registers() -> Option<(u8, u8, u8, u8)> {
    use crate::driver::wmi_ec::{
        wmi_read_ec, ADDR_DB_CTRL1, ADDR_DB_FLAG1, ADDR_DB_WATTS1, ADDR_TGP_OFFSET,
    };
    Some((
        wmi_read_ec(ADDR_DB_CTRL1)?,
        wmi_read_ec(ADDR_TGP_OFFSET)?,
        wmi_read_ec(ADDR_DB_FLAG1)?,
        wmi_read_ec(ADDR_DB_WATTS1)?,
    ))
}

'''

EDITS = [
    {
        "path": "src-tauri/src/system/power/mod.rs",
        "old": CALL_ANCHOR,
        "new": CALL_PATCHED,
        "label": "spawn deferred GPU contract restore for Custom mode",
    },
    {
        "path": "src-tauri/src/system/power/mod.rs",
        "old": FUNCS_ANCHOR,
        "new": FUNCS_BLOCK + FUNCS_ANCHOR,
        "label": "add deferred GPU contract restore task",
    },
]


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: fix_startup_gpu_contract.py <openrevo-source-root>")
    root = Path(sys.argv[1]).resolve()
    by_path = {}
    for e in EDITS:
        path = root / e["path"]
        if not path.is_file():
            raise SystemExit("missing source: " + str(path))
        if path not in by_path:
            by_path[path] = path.read_text(encoding="utf-8")
        current = by_path[path]
        count = current.count(e["old"])
        if count != 1:
            raise SystemExit(
                f"r10 anchor mismatch {e['label']} ({path}): {count}"
            )
        by_path[path] = current.replace(e["old"], e["new"], 1)
    for path, content in by_path.items():
        path.write_text(content, encoding="utf-8", newline="\n")
    total = sum(s.count("GPU_CONTRACT") for s in by_path.values())
    print(
        f"r10: wired deferred GPU contract restore; {len(EDITS)} exact edits across "
        f"{len(by_path)} files, {total} GPU_CONTRACT log anchors"
    )


if __name__ == "__main__":
    main()
