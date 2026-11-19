#!/usr/bin/env python3
"""Restore r5's three draggable SVG temperature lines in the GM6IX8X r7 view.
Keeps unchanged original chart layout; only adds the purple stop threshold."""
from pathlib import Path
import sys

def edit(path, old, new, why):
    s = path.read_text(encoding="utf-8")
    count = s.count(old)
    if count != 1:
        raise SystemExit(f"r5 chart compatibility mismatch {why}: found {count}")
    path.write_text(s.replace(old, new, 1), encoding="utf-8", newline="\n")
    print("restored:", why)

def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: restore_r5_curve.py <openrevo-root>")
    root = Path(sys.argv[1])
    curve = root / "src/components/water_cooler/CoolerCurvePanel.tsx"
    if not curve.exists():
        raise SystemExit("Water cooler chart missing")
    edit(curve,
        '  pumpStartTemp?: number;\n  pumpTurboTemp?: number;',
        '  pumpStartTemp?: number;\n  pumpStopTemp?: number;\n  showStopHandle?: boolean;\n  pumpTurboTemp?: number;',
        "Add third control and model-specific visibility props")
    edit(curve,
        'onPumpThresholdsChange?: (startTemp: number, turboTemp: number, committed: boolean) => void;',
        'onPumpThresholdsChange?: (stopTemp: number, startTemp: number, turboTemp: number, committed: boolean) => void;',
        "Three temperature callback type")
    edit(curve,
        '  pumpStartTemp,\n  pumpTurboTemp,',
        '  pumpStartTemp,\n  pumpStopTemp,\n  showStopHandle,\n  pumpTurboTemp,',
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
              低温停转区 (≤{showStopHandle ? displayStop : displayStart - 5}°C)''',
        "Correctly label actual shutdown threshold")
    edit(curve,
        '''          {/* 启泵阈值手柄杆 (可左右拖拽) */}''',
        '''          {showStopHandle && (
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
        '''          {showStopHandle && (
            <text x={xStop} y="116" fill="#a78bfa" fontSize="9" fontWeight="800" textAnchor="middle">
              {displayStop}°停泵
            </text>
          )}
          <text x={xStart} y="134" fill="#34d399" fontSize="9" fontWeight="800" textAnchor="middle">''',
        "Display stop threshold on chart bottom without hiding start")


if __name__ == "__main__":
    main()
