#!/usr/bin/env python3
"""r8: reconcile GM6IX8X adaptive water-cooler UI with r7 actual controller.
Only touches four water-cooler frontend files, never GPU Dynamic Boost or EC.
Run after r7/apply_dual_loop.py and r7/restore_r5_curve.py.
"""
import sys
from pathlib import Path

EDITS = [
  {
    "path": "src/components/water_cooler/CoolerHeaderTelemetry.tsx",
    "old": ">核心综合温度 max(CPU, GPU)</span>",
    "new": ">{coolerData.dual_loop_model ? 'CPU / GPU 双源监测' : '核心综合温度 max(CPU, GPU)'}</span>",
    "label": "header title"
  },
  {
    "path": "src/components/water_cooler/CoolerHeaderTelemetry.tsx",
    "old": "{liveMaxTemp} °C\n            <span style={{ fontSize: '9px', color: 'var(--text-dim)', fontWeight: 500, marginLeft: '4px' }}>\n              (CPU {cpuTemp}° / GPU {gpuTemp}°)\n            </span>",
    "new": "{coolerData.dual_loop_model ? (\n              <span style={{ fontSize: '12px' }}>\n                CPU {cpuTemp > 0 ? cpuTemp : '--'}° / GPU {gpuTemp > 0 ? gpuTemp : '--'}°\n              </span>\n            ) : (\n              <>\n                {liveMaxTemp} °C\n                <span style={{ fontSize: '9px', color: 'var(--text-dim)', fontWeight: 500, marginLeft: '4px' }}>\n                  (CPU {cpuTemp > 0 ? cpuTemp : '--'}° / GPU {gpuTemp > 0 ? gpuTemp : '--'}°)\n                </span>\n              </>\n            )}",
    "label": "header true sensors"
  },
  {
    "path": "src/components/water_cooler/CoolerPresetCards.tsx",
    "old": "import React from 'react';",
    "new": "import React from 'react';\nimport type { CoolerTelemetry } from './coolerTypes';",
    "label": "card import"
  },
  {
    "path": "src/components/water_cooler/CoolerPresetCards.tsx",
    "old": "  liveInterpolated: { duty: number; volt: number };\n  onUpdateStrategy:",
    "new": "  liveInterpolated: { duty: number; volt: number };\n  coolerData: CoolerTelemetry;\n  onUpdateStrategy:",
    "label": "card props"
  },
  {
    "path": "src/components/water_cooler/CoolerPresetCards.tsx",
    "old": "  liveInterpolated,\n  onUpdateStrategy,",
    "new": "  liveInterpolated,\n  coolerData,\n  onUpdateStrategy,",
    "label": "card destructure"
  },
  {
    "path": "src/components/water_cooler/CoolerPresetCards.tsx",
    "old": "}) => {\n  return (",
    "new": "}) => {\n  const dualLoop = coolerData.dual_loop_model === true;\n  const tier = coolerData.pump_tier ?? coolerData.pump_voltage;\n  const tierLabel = tier === 0 ? '停泵' : tier === 1 ? '静音' : tier === 3 ? '狂暴' : '标准巡航';\n  return (",
    "label": "card loop"
  },
  {
    "path": "src/components/water_cooler/CoolerPresetCards.tsx",
    "old": "              温控随动\n",
    "new": "              {dualLoop ? '双源热负荷' : '温控随动'}\n",
    "label": "card badge"
  },
  {
    "path": "src/components/water_cooler/CoolerPresetCards.tsx",
    "old": "            依据核心温度动态调控，<strong style={{ color: 'var(--status-ok)' }}>&lt;55°C 风扇停转</strong>",
    "new": "            {dualLoop\n              ? 'CPU/GPU 独立温度平滑 + 热负荷累积；启停带持续确认'\n              : <>依据核心温度动态调控，<strong style={{ color: 'var(--status-ok)' }}>&lt;55°C 风扇停转</strong></>}",
    "label": "card description"
  },
  {
    "path": "src/components/water_cooler/CoolerPresetCards.tsx",
    "old": "            <Zap size={10} /> 随动: {liveMaxTemp}°C → 风扇 {liveInterpolated.duty}% | 水泵 {\n              liveInterpolated.volt >= 11 || liveInterpolated.volt === 3\n                ? '极限狂暴'\n                : liveInterpolated.volt === 0\n                ? '停机'\n                : '标准巡航'\n            }",
    "new": "            <Zap size={10} />\n            {dualLoop\n              ? (coolerData.connected\n                  ? <>实时指令：风扇 {coolerData.fan_duty}% | 水泵 {tierLabel}</>\n                  : '等待水冷箱连接')\n              : <>随动: {liveMaxTemp}°C → 风扇 {liveInterpolated.duty}% | 水泵 {\n                  liveInterpolated.volt >= 11 || liveInterpolated.volt === 3\n                    ? '极限狂暴'\n                    : liveInterpolated.volt === 0\n                    ? '停机'\n                    : '标准巡航'\n                }</>}",
    "label": "card real commands"
  },
  {
    "path": "src/components/WaterCoolerView.tsx",
    "old": "        <CoolerPresetCards\n          strategy={coolerData.strategy}\n",
    "new": "        <CoolerPresetCards\n          strategy={coolerData.strategy}\n          coolerData={coolerData}\n",
    "label": "view connect card"
  },
  {
    "path": "src/components/WaterCoolerView.tsx",
    "old": "        <CoolerCurvePanel\n          strategy={coolerData.strategy}\n",
    "new": "        <CoolerCurvePanel\n          strategy={coolerData.strategy}\n          dualLoopModel={coolerData.dual_loop_model}\n",
    "label": "view connect curve"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "interface CoolerCurvePanelProps {\n  strategy?: string;\n",
    "new": "interface CoolerCurvePanelProps {\n  strategy?: string;\n  dualLoopModel?: boolean;\n",
    "label": "curve prop"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "export const CoolerCurvePanel: React.FC<CoolerCurvePanelProps> = ({\n  strategy,\n",
    "new": "export const CoolerCurvePanel: React.FC<CoolerCurvePanelProps> = ({\n  strategy,\n  dualLoopModel,\n",
    "label": "curve destructure"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "}) => {\n  const containerRef",
    "new": "}) => {\n  const isDualProfile = dualLoopModel === true;\n  const containerRef",
    "label": "curve mode"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "自适应温控曲线 (Fan Duty & Pump Voltage vs Temp)",
    "new": "{isDualProfile ? '双源智慧温控阈值（青线仅供参考）' : '自适应温控曲线 (Fan Duty & Pump Voltage vs Temp)'}",
    "label": "curve label"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "            支持节点与水泵阈值拖拽",
    "new": "            {isDualProfile ? '紫 / 绿 / 红三条阈值线可拖动 · 青线不参与智能调速' : '支持节点与水泵阈值拖拽'}",
    "label": "curve badge"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "<span>风扇 (0%~100%)</span>",
    "new": "<span>{isDualProfile ? '风扇参考曲线（非实际输出）' : '风扇 (0%~100%)'}</span>",
    "label": "curve legend fan"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "              style={{ cursor: 'grab' }}\n              onMouseDown={(e) => startDragHandle(e, idx)}",
    "new": "              style={{ cursor: isDualProfile ? 'not-allowed' : 'grab', opacity: isDualProfile ? 0.4 : 1 }}\n              onMouseDown={isDualProfile ? undefined : (e) => startDragHandle(e, idx)}",
    "label": "curve inactive handles"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "              低温停转区 (&lt;{displayStart}°C)",
    "new": "              {isDualProfile ? '低温参考（停泵还需持续冷却）' : <>低温停转区 (&lt;{displayStart}°C)</>}",
    "label": "curve low label"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "              水泵标准巡航区 ({displayStart}°C~{displayTurbo}°C)",
    "new": "              {isDualProfile ? '标准运行参考（不按单温度切档）' : <>水泵标准巡航区 ({displayStart}°C~{displayTurbo}°C)</>}",
    "label": "curve mid label"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "              水泵极限狂暴区 (≥{displayTurbo}°C)",
    "new": "              {isDualProfile ? '高温参考（热负荷 / 紧急保护）' : <>水泵极限狂暴区 (≥{displayTurbo}°C)</>}",
    "label": "curve high label"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "          {/* 实时温度探针 */}\n          <g>",
    "new": "          {/* The MAX-temperature probe would misrepresent dual-loop thermal-debt control. */}\n          {!isDualProfile && (\n          <g>",
    "label": "hide max probe start"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "          </g>\n        </svg>\n      </div>\n\n      {/* 曲线底部预设模板 */}",
    "new": "          </g>\n          )}\n        </svg>\n      </div>\n\n      {/* 曲线底部预设模板 */}",
    "label": "hide max probe end"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "            <span>实时探针</span>",
    "new": "            <span>{isDualProfile ? '智慧模式不采用最高温度探针' : '实时探针'}</span>",
    "label": "hide old probe legend"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "                key={t.id}\n                onClick={() => onApplyTemplate(t.id as any)}",
    "new": "                key={t.id}\n                disabled={isDualProfile}\n                title={isDualProfile ? '双源智慧算法不使用单温度风扇曲线，请直接拖动上方的停泵/启泵/狂暴竖线' : undefined}\n                onClick={() => onApplyTemplate(t.id as any)}",
    "label": "disable fake preset"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "                  cursor: 'pointer',\n                  display: 'inline-flex',",
    "new": "                  cursor: isDualProfile ? 'not-allowed' : 'pointer',\n                  opacity: isDualProfile ? 0.45 : 1,\n                  display: 'inline-flex',",
    "label": "preset button cursor"
  },
  {
    "path": "src/components/water_cooler/CoolerCurvePanel.tsx",
    "old": "          <span>内置 3°C 迟滞滤波防抖</span>",
    "new": "          <span>{isDualProfile ? '双源平滑 + 热负荷累积 + 延时启停（曲线预设不生效）' : '内置 3°C 迟滞滤波防抖'}</span>",
    "label": "curve hint"
  }
]

def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: fix_adaptive_ui.py <openrevo-source-root>")
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
            raise SystemExit(f"r8 anchor mismatch {e['label']} ({path}): {count}")
        by_path[path] = current.replace(e["old"], e["new"], 1)
    for path, content in by_path.items():
        path.write_text(content, encoding="utf-8", newline="\n")
    print(f"r8: applied {len(EDITS)} exact edits to {len(by_path)} water-cooler UI files; GPU DB untouched")

if __name__ == "__main__":
    main()
