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

    # NVML implementation is imported from upstream PR #133 before running this script.
    nvml = root / "src-tauri/src/driver/nvml.rs"
    mod = root / "src-tauri/src/driver/mod.rs"
    if not nvml.is_file() or "pub mod nvml;" not in mod.read_text(encoding="utf-8"):
        raise SystemExit("NVML upstream patch missing; refusing to continue")

    replace_exact(gpu,
        '        let is_nv = probe_nvidia_presence_registry();',
        '        // Some NVIDIA laptops lack the OEM/DisplayClass registry keys.\n'
        '        // Check the physical PCI device as a second source and NVML as a\n'
        '        // final safe detection route (context drops immediately).\n'
        '        let is_nv = probe_nvidia_presence_registry()\n'
        '            || detect_dgpu_from_pci_enum().is_some()\n'
        '            || crate::driver::nvml::NvmlContext::open().is_ok();',
        "Robust NVIDIA presence detection via registry, PCI PnP and NVML")

    replace_exact(gpu,
        '            temp: AtomicU32::new(35),',
        '            temp: AtomicU32::new(0),',
        "Never show a hardcoded fake GPU temperature")

    replace_exact(gpu,
        '        let output = Command::new("nvidia-smi")\n'
        '            .creation_flags(CREATE_NO_WINDOW)\n'
        '            .args([\n'
        '                "--query-gpu=name,clocks.current.graphics,clocks.current.memory,temperature.gpu,utilization.gpu,memory.total,memory.used,power.draw",',
        '        let output = find_nvidia_smi_command()\n'
        '            .args([\n'
        '                "--query-gpu=name,clocks.current.graphics,clocks.current.memory,temperature.gpu,utilization.gpu,memory.total,memory.used,power.draw",',
        "Locate NVIDIA SMI executable reliably when NVML is unavailable")

    # Reject implausible GPU temperature samples; display '--' rather than 0C.
    replace_exact(gpu,
        '                inner.temp.store(s.temp_c, Ordering::SeqCst);',
        '                if (10..=110).contains(&s.temp_c) {\n'
        '                    inner.temp.store(s.temp_c, Ordering::SeqCst);\n'
        '                } else {\n'
        '                    inner.temp.store(0, Ordering::SeqCst);\n'
        '                }',
        "Validate NVML GPU temperature before publishing")

    replace_exact(gpu,
        '                // 主动释放：Drop 会调用 nvmlShutdown，解除驱动侧的活动引用\n'
        '                ctx = None;',
        '                // No valid live reading exists for a sleeping/disconnected GPU.\n'
        '                inner.temp.store(0, Ordering::SeqCst);\n'
        '                // 主动释放：Drop 会调用 nvmlShutdown，解除驱动侧的活动引用\n'
        '                ctx = None;',
        "Clear stale NVML GPU temperature on disconnect")

    # Legacy fallback must also explicitly detect parse failures.
    replace_exact(gpu,
        '                consecutive_failures = 0;\n'
        '                let text = String::from_utf8_lossy(&out.stdout);',
        '                let text = String::from_utf8_lossy(&out.stdout);',
        "Do not treat malformed nvidia-smi data as success")

    replace_exact(gpu,
        '                if parts.len() >= 7 {\n'
        '                    let name = parts[0];',
        '                if parts.len() >= 7 {\n'
        '                    if let Ok(t) = parts[3].parse::<u32>() {\n'
        '                        if (10..=110).contains(&t) {\n'
        '                            inner.temp.store(t, Ordering::SeqCst);\n'
        '                            consecutive_failures = 0;\n'
        '                        } else {\n'
        '                            consecutive_failures = consecutive_failures.saturating_add(1);\n'
        '                        }\n'
        '                    } else {\n'
        '                        consecutive_failures = consecutive_failures.saturating_add(1);\n'
        '                    }\n'
        '                    let name = parts[0];',
        "Validate legacy temperature telemetry")

    replace_exact(gpu,
        '                    if let Ok(t) = parts[3].parse::<u32>() {\n'
        '                        inner.temp.store(t, Ordering::SeqCst);\n'
        '                    }\n'
        '                    if let Ok(u) = parts[4].parse::<u32>() {',
        '                    if let Ok(u) = parts[4].parse::<u32>() {',
        "Avoid overwriting validated GPU telemetry")

    replace_exact(gpu,
        '                }\n'
        '            } else {\n'
        '                consecutive_failures = consecutive_failures.saturating_add(1);\n'
        '            }\n'
        '        } else {\n'
        '            consecutive_failures = consecutive_failures.saturating_add(1);\n'
        '        }\n'
        '    }\n'
        '}\n\n'
        'static NVIDIA_POWER_LIMITS_CACHE:',
        '                } else {\n'
        '                    consecutive_failures = consecutive_failures.saturating_add(1);\n'
        '                }\n'
        '            } else {\n'
        '                consecutive_failures = consecutive_failures.saturating_add(1);\n'
        '            }\n'
        '        } else {\n'
        '            consecutive_failures = consecutive_failures.saturating_add(1);\n'
        '        }\n'
        '        if consecutive_failures >= 3 {\n'
        '            if inner.temp.swap(0, Ordering::SeqCst) != 0 {\n'
        '                crate::log_warn!("GPU_BRIDGE", "GPU sample lost in nvidia-smi fallback; temperature unavailable");\n'
        '            }\n'
        '        }\n'
        '    }\n'
        '}\n\n'
        'static NVIDIA_POWER_LIMITS_CACHE:',
        "Avoid stale legacy GPU temperature")

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
        // Missing both sensors must not silently turn off a connected water pump.
        return if cpu < 10 { 65 } else { cpu.max(30) };
    };
    // Keep CPU high-temperature escalation while avoiding transient CPU-only spikes.
    let cpu_guard = if cpu >= 95 { cpu } else if cpu >= 85 { 80 }
        else if cpu >= 75 { 65 } else if cpu >= 60 { 55 } else { 30 };
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
        assert_eq!(calculate_gpu_first_cooler_temp(82, Some(43)), 65);
        assert_eq!(calculate_gpu_first_cooler_temp(90, Some(43)), 80);
        assert_eq!(calculate_gpu_first_cooler_temp(96, Some(43)), 96);
        assert_eq!(calculate_gpu_first_cooler_temp(70, Some(43)), 55);
    }
    #[test]
    fn falls_back_to_cpu_when_gpu_unavailable() {
        assert_eq!(calculate_gpu_first_cooler_temp(78, None), 78);
        assert_eq!(calculate_gpu_first_cooler_temp(0, None), 65);
    }
}"""
    replace_exact(cooler, old_cooler, new_cooler, "GPU-first cooler strategy with CPU guardrails")

    replace_exact(ui,
        '  const liveMaxTemp = Math.max(status.cpu_temp || 0, status.gpu_temp || 0) || 45;',
        '  // Match the Rust BLE controller smart-temperature calculation.\n'
        '  const cpuMeasured = Math.max(0, status.cpu_temp || 0);\n'
        '  const gpuMeasured = status.gpu_temp > 0 && status.gpu_temp <= 110 ? status.gpu_temp : null;\n'
        '  const cpuGuard = cpuMeasured >= 95 ? cpuMeasured : cpuMeasured >= 85 ? 80 : cpuMeasured >= 75 ? 65 : cpuMeasured >= 60 ? 55 : 30;\n'
        '  const liveMaxTemp = gpuMeasured === null ? (cpuMeasured < 10 ? 65 : Math.max(30, cpuMeasured)) : Math.max(30, gpuMeasured, cpuGuard);',
        "Keep water-cooler chart in sync with controller")
    hdr = root / "src/components/water_cooler/CoolerHeaderTelemetry.tsx"
    replace_exact(hdr,
        '核心综合温度 max(CPU, GPU)',
        '水冷智能控制温度（GPU 优先 / CPU 保护）',
        "Label reflects GPU-first guardrail logic")
    replace_exact(hdr,
        '(CPU {cpuTemp}° / GPU {gpuTemp}°)',
        '(CPU {cpuTemp > 0 ? cpuTemp : "--"}° / GPU {gpuTemp > 0 ? gpuTemp : "--"}°)',
        "Show unavailable GPU temperature as -- instead of fake 0C")
    print("All source changes applied. No hardware access has occurred.")


if __name__ == "__main__":
    main()
