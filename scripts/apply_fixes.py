#!/usr/bin/env python3
"""Apply reviewable minimal GPU telemetry + BLE smart-cooler fix to pinned OpenRevo source.

Only edits exact, single-match source fragments. Exits with an error on drift.
Does not interact with hardware or modify installed applications.
"""
from pathlib import Path
import sys


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    s = path.read_text(encoding="utf-8")
    count = s.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match in {path}, found {count}")
    path.write_text(s.replace(old, new, 1), encoding="utf-8", newline="\n")
    print(f"Patched {label}: {path}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python apply_fixes.py <openrevo-source-root>")
    root = Path(sys.argv[1]).resolve()
    gpu = root / "src-tauri/src/driver/gpu_bridge.rs"
    cooler = root / "src-tauri/src/driver/ble_cooler.rs"
    ui = root / "src/components/WaterCoolerView.tsx"
    for p in (gpu, cooler, ui):
        if not p.is_file():
            raise SystemExit(f"Source not found: {p}")

    replace_exact(gpu,
        '            temp: AtomicU32::new(35),',
        '            temp: AtomicU32::new(0),',
        "GPU initial temperature unavailable instead of fake 35C")

    replace_exact(gpu,
        '                let output = Command::new("nvidia-smi")\n'
        '                    .creation_flags(CREATE_NO_WINDOW)\n'
        '                    .args([',
        '                let output = find_nvidia_smi_command()\n'
        '                    .args([',
        "Use existing NVIDIA executable resolver")

    replace_exact(gpu,
        '                    if out.status.success() {\n'
        '                        consecutive_failures = 0;\n'
        '                        let text = String::from_utf8_lossy(&out.stdout);',
        '                    if out.status.success() {\n'
        '                        let text = String::from_utf8_lossy(&out.stdout);',
        "Do not count malformed telemetry as success")

    replace_exact(gpu,
        '                        if parts.len() >= 7 {\n'
        '                            let name = parts[0];',
        '                        if parts.len() >= 7 {\n'
        '                            // Only a valid NVIDIA sample marks temperature telemetry healthy.\n'
        '                            if let Ok(t) = parts[3].parse::<u32>() {\n'
        '                                if (10..=110).contains(&t) {\n'
        '                                    inner.temp.store(t, Ordering::SeqCst);\n'
        '                                    consecutive_failures = 0;\n'
        '                                } else {\n'
        '                                    consecutive_failures = consecutive_failures.saturating_add(1);\n'
        '                                }\n'
        '                            } else {\n'
        '                                consecutive_failures = consecutive_failures.saturating_add(1);\n'
        '                            }\n'
        '                            let name = parts[0];',
        "Validate actual temperature sample")

    replace_exact(gpu,
        '                            if let Ok(t) = parts[3].parse::<u32>() {\n'
        '                                inner.temp.store(t, Ordering::SeqCst);\n'
        '                            }\n'
        '                            if let Ok(u) = parts[4].parse::<u32>() {',
        '                            if let Ok(u) = parts[4].parse::<u32>() {',
        "Remove unchecked temperature overwrite")

    replace_exact(gpu,
        '                                    inner.power_dw.store(dw, Ordering::SeqCst);\n'
        '                                }\n'
        '                            }\n'
        '                        }\n'
        '                    } else {',
        '                                    inner.power_dw.store(dw, Ordering::SeqCst);\n'
        '                                }\n'
        '                            }\n'
        '                        } else {\n'
        '                            consecutive_failures = consecutive_failures.saturating_add(1);\n'
        '                        }\n'
        '                    } else {',
        "Track malformed short rows")

    replace_exact(gpu,
        '                } else {\n'
        '                    consecutive_failures = consecutive_failures.saturating_add(1);\n'
        '                }\n'
        '            }\n'
        '        });\n'
        '    }\n\n'
        '    pub fn get_gpu_count(&self) -> u32 {',
        '                } else {\n'
        '                    consecutive_failures = consecutive_failures.saturating_add(1);\n'
        '                }\n'
        '                // Invalid or stale GPU readings must not drive external cooling.\n'
        '                if consecutive_failures >= 3 && inner.temp.swap(0, Ordering::SeqCst) != 0 {\n'
        '                    crate::log_warn!("GPU_BRIDGE", "GPU temperature sample stale; reporting unavailable");\n'
        '                }\n'
        '            }\n'
        '        });\n'
        '    }\n\n'
        '    pub fn get_gpu_count(&self) -> u32 {',
        "Clear stale temperature after repeated failures")

    old_cooler = """pub fn get_current_max_temp() -> u8 {
    let cpu_t = crate::system::cpu_monitor::get_global_cpu_monitor().get_temp().max(0) as u8;
    let gpu_t = {
        let gpu = crate::driver::gpu_bridge::get_global_gpu();
        let g = gpu.lock();
        if g.get_gpu_count() > 0 { g.get_temp(0) as u8 } else { 0 }
    };
    cpu_t.max(gpu_t).max(30)
}"""
    new_cooler = """// Existing BLE callers keep this name; smart mode now uses GPU-first mapping.
pub fn get_current_max_temp() -> u8 {
    let cpu_t = crate::system::cpu_monitor::get_global_cpu_monitor().get_temp().clamp(0, 110) as u8;
    let gpu_t = {
        let gpu = crate::driver::gpu_bridge::get_global_gpu();
        let g = gpu.lock();
        if g.get_gpu_count() > 0 {
            let t = g.get_temp(0);
            if (10..=110).contains(&t) { Some(t as u8) } else { None }
        } else { None }
    };
    calculate_gpu_first_cooler_temp(cpu_t, gpu_t)
}

fn calculate_gpu_first_cooler_temp(cpu: u8, gpu: Option<u8>) -> u8 {
    let Some(gpu) = gpu else {
        // On a sleeping or unreadable GPU, retain CPU-driven cooling.
        return cpu.max(30);
    };
    // Keep CPU high-temperature escalation while avoiding transient CPU-only spikes.
    let cpu_guard = if cpu >= 95 { cpu } else if cpu >= 85 { 80 }
        else if cpu >= 75 { 60 } else { 30 };
    gpu.max(cpu_guard).max(30)
}

#[cfg(test)]
mod gpu_first_cooler_temp_tests {
    use super::calculate_gpu_first_cooler_temp;

    #[test]
    fn uses_gpu_during_ordinary_loads() {
        assert_eq!(calculate_gpu_first_cooler_temp(68, Some(60)), 60);
    }
    #[test]
    fn preserves_cpu_guardrails() {
        assert_eq!(calculate_gpu_first_cooler_temp(82, Some(43)), 60);
        assert_eq!(calculate_gpu_first_cooler_temp(90, Some(43)), 80);
        assert_eq!(calculate_gpu_first_cooler_temp(96, Some(43)), 96);
    }
    #[test]
    fn falls_back_to_cpu_when_gpu_unavailable() {
        assert_eq!(calculate_gpu_first_cooler_temp(78, None), 78);
    }
}"""
    replace_exact(cooler, old_cooler, new_cooler, "GPU-first cooler strategy with CPU guardrails")

    replace_exact(ui,
        '  const liveMaxTemp = Math.max(status.cpu_temp || 0, status.gpu_temp || 0) || 45;',
        '  // Match the Rust BLE controller smart-temperature calculation.\n'
        '  const cpuMeasured = Math.max(0, status.cpu_temp || 0);\n'
        '  const gpuMeasured = status.gpu_temp > 0 && status.gpu_temp <= 110 ? status.gpu_temp : null;\n'
        '  const cpuGuard = cpuMeasured >= 95 ? cpuMeasured : cpuMeasured >= 85 ? 80 : cpuMeasured >= 75 ? 60 : 30;\n'
        '  const liveMaxTemp = gpuMeasured === null ? Math.max(30, cpuMeasured) : Math.max(30, gpuMeasured, cpuGuard);',
        "Keep water-cooler chart in sync with controller")
    print("All source changes applied. No hardware access has occurred.")


if __name__ == "__main__":
    main()
