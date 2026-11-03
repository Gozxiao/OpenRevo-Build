#!/usr/bin/env python3
"""Extract ACTUAL Rust cooling state machine into a stand-alone std-only test harness.

This avoids unrelated WinRT DLL startup problems in the full OpenRevo test binary,
while still executing the exact state machine and tests shipped in the installer.
"""
from pathlib import Path
import sys

def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: extract_cooler_tests.py <openrevo_source> <standalone_output.rs>")
    src = Path(sys.argv[1]) / "src-tauri/src/driver/ble_cooler.rs"
    out = Path(sys.argv[2])
    s = src.read_text(encoding="utf-8")
    a = s.find("/// GPU-only loop on confirmed GM6PX8X hardware.")
    b = s.find("\npub fn calculate_strategy_params(", a)
    if a < 0 or b < a or "mod gpu_only_pump_guard_tests" not in s[a:b]:
        raise SystemExit("R4 Rust state machine and its tests not found")
    prologue = """use std::time::{Instant, Duration};
#[derive(Copy, Clone, PartialEq, Eq, Debug)]
enum CoolerPumpTier { Stop, Silent, Standard, Turbo }

"""
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(prologue + s[a:b] + "\n",encoding="utf-8")
    print(f"Extracted actual GM6PX8X state machine and Rust tests to {out}")

if __name__ == "__main__":
    main()
