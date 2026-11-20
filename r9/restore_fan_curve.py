#!/usr/bin/env python3
"""r9: restore editable radiator fan curve and expose independent CPU/GPU probes."""
import sys
from pathlib import Path

EDITS = [
  {
    "path": "src/components/WaterCoolerView.tsx",
    "old": "          dualLoopModel={coolerData.dual_loop_model}\n          activeCurve={activeCurve}",
    "new": "          dualLoopModel={coolerData.dual_loop_model}\n          cpuTemp={status.cpu_temp}\n          gpuTemp={status.gpu_temp}\n          actualFanDuty={coolerData.fan_duty}\n          activeCurve={activeCurve}",
    "label": "pass independent sensor temperatures and fan command"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "  dualLoopModel?: boolean;\n  activeCurve:",
    "new": "  dualLoopModel?: boolean;\n  cpuTemp?: number;\n  gpuTemp?: number;\n  actualFanDuty?: number;\n  activeCurve:",
    "label": "sensor props"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "  dualLoopModel,\n  activeCurve,",
    "new": "  dualLoopModel,\n  cpuTemp,\n  gpuTemp,\n  actualFanDuty,\n  activeCurve,",
    "label": "sensor destructuring"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "  const probeX = tempToX(liveMaxTemp);\n  const probeY = dutyToY(liveInterpolated.duty);",
    "new": "  const probeX = tempToX(liveMaxTemp);\n  const probeY = dutyToY(liveInterpolated.duty);\n  const curveDutyAt = (temp: number) => {\n    if (!sortedPts.length) return 65;\n    if (temp <= sortedPts[0].temp) return sortedPts[0].fan_duty;\n    for (let i = 0; i < sortedPts.length - 1; i++) {\n      const a = sortedPts[i];\n      const b = sortedPts[i + 1];\n      if (temp <= b.temp) {\n        const ratio = (temp - a.temp) / Math.max(1, b.temp - a.temp);\n        return Math.round(a.fan_duty + ratio * (b.fan_duty - a.fan_duty));\n      }\n    }\n    return sortedPts[sortedPts.length - 1].fan_duty;\n  };\n  const cpuProbeTemp = Math.max(30, Math.min(100, cpuTemp && cpuTemp > 0 ? cpuTemp : 45));\n  const gpuProbeTemp = Math.max(30, Math.min(100, gpuTemp && gpuTemp > 0 ? gpuTemp : 45));\n  const cpuProbeX = tempToX(cpuProbeTemp);\n  const gpuProbeX = tempToX(gpuProbeTemp);\n  const cpuProbeDuty = curveDutyAt(cpuProbeTemp);\n  const gpuProbeDuty = curveDutyAt(gpuProbeTemp);",
    "label": "dual source probe interpolation"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "{isDualProfile ? '双源智慧温控阈值（青线仅供参考）' : '自适应温控曲线 (Fan Duty & Pump Voltage vs Temp)'}",
    "new": "{isDualProfile ? '双源智慧温控：青线调风扇 / 竖线调水泵' : '自适应温控曲线 (Fan Duty & Pump Voltage vs Temp)'}",
    "label": "honest chart title"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "{isDualProfile ? '紫 / 绿 / 红三条阈值线可拖动 · 青线不参与智能调速' : '支持节点与水泵阈值拖拽'}",
    "new": "{isDualProfile ? '青色曲线控制风扇 · 紫/绿/红竖线控制水泵' : '支持节点与水泵阈值拖拽'}",
    "label": "honest chart hint"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "{isDualProfile ? '风扇参考曲线（非实际输出）' : '风扇 (0%~100%)'}",
    "new": "{isDualProfile ? '风扇曲线（CPU/GPU分别查表）' : '风扇 (0%~100%)'}",
    "label": "fan legend"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "style={{ cursor: isDualProfile ? 'not-allowed' : 'grab', opacity: isDualProfile ? 0.4 : 1 }}\n              onMouseDown={isDualProfile ? undefined : (e) => startDragHandle(e, idx)}",
    "new": "style={{ cursor: 'grab' }}\n              onMouseDown={(e) => startDragHandle(e, idx)}",
    "label": "restore curve node dragging"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "          {/* The MAX-temperature probe would misrepresent dual-loop thermal-debt control. */}\n          {!isDualProfile && (\n          <g>",
    "new": "          {isDualProfile ? (\n            <>\n              <g>\n                <line x1={cpuProbeX} y1=\"15\" x2={cpuProbeX} y2=\"120\" stroke=\"#f59e0b\" strokeWidth=\"1.6\" strokeDasharray=\"3,2\" />\n                <circle cx={cpuProbeX} cy={dutyToY(cpuProbeDuty)} r=\"5\" fill=\"#f59e0b\" stroke=\"#fff\" strokeWidth=\"1.2\" />\n                <g transform={'translate(' + cpuProbeX + ', 26)'}>\n                  <rect x=\"-34\" y=\"-17\" width=\"68\" height=\"14\" rx=\"3\" fill=\"rgba(15,23,42,0.95)\" stroke=\"#f59e0b\" strokeWidth=\"0.8\" />\n                  <text x=\"0\" y=\"-7\" fill=\"#fff\" fontSize=\"8.5\" fontWeight=\"700\" textAnchor=\"middle\">CPU {Math.round(cpuProbeTemp)}° / {cpuProbeDuty}%</text>\n                </g>\n              </g>\n              <g>\n                <line x1={gpuProbeX} y1=\"15\" x2={gpuProbeX} y2=\"120\" stroke=\"#a78bfa\" strokeWidth=\"1.6\" strokeDasharray=\"3,2\" />\n                <circle cx={gpuProbeX} cy={dutyToY(gpuProbeDuty)} r=\"5\" fill=\"#a78bfa\" stroke=\"#fff\" strokeWidth=\"1.2\" />\n                <g transform={'translate(' + gpuProbeX + ', 48)'}>\n                  <rect x=\"-34\" y=\"-17\" width=\"68\" height=\"14\" rx=\"3\" fill=\"rgba(15,23,42,0.95)\" stroke=\"#a78bfa\" strokeWidth=\"0.8\" />\n                  <text x=\"0\" y=\"-7\" fill=\"#fff\" fontSize=\"8.5\" fontWeight=\"700\" textAnchor=\"middle\">GPU {Math.round(gpuProbeTemp)}° / {gpuProbeDuty}%</text>\n                </g>\n              </g>\n            </>\n          ) : (\n          <g>",
    "label": "replace misleading max probe with dual probes"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "<span>{isDualProfile ? '智慧模式不采用最高温度探针' : '实时探针'}</span>",
    "new": "<span>{isDualProfile ? 'CPU / GPU 独立曲线需求' : '实时探针'}</span>",
    "label": "dual sensor probe legend"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "                disabled={isDualProfile}\n                title={isDualProfile ? '双源智慧算法不使用单温度风扇曲线，请直接拖动上方的停泵/启泵/狂暴竖线' : undefined}\n",
    "new": "",
    "label": "restore fan curve presets"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "                  cursor: isDualProfile ? 'not-allowed' : 'pointer',\n                  opacity: isDualProfile ? 0.45 : 1,\n",
    "new": "                  cursor: 'pointer',\n",
    "label": "restore preset interaction"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "{isDualProfile ? '双源平滑 + 热负荷累积 + 延时启停（曲线预设不生效）' : '内置 3°C 迟滞滤波防抖'}",
    "new": "{isDualProfile ? '风扇：CPU/GPU平滑温度分别查曲线，取较高需求；水泵：双源热负荷独立控制' : '内置 3°C 迟滞滤波防抖'}",
    "label": "separate fan and pump algorithms"
  }
]
def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: restore_fan_curve.py <openrevo-source-root>")
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
            raise SystemExit(f"r9 anchor mismatch {e['label']} ({path}): {count}")
        by_path[path] = current.replace(e["old"], e["new"], 1)
    for path, content in by_path.items():
        path.write_text(content, encoding="utf-8", newline="\n")
    print(f"r9: restored editable fan curve and dual-source probes; {len(EDITS)} exact edits across {len(by_path)} files")

if __name__ == "__main__":
    main()
