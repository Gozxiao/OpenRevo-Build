/* OpenRevo 游戏性能实验室 — PresentMon CSV 分析器，离线、无网络依赖。 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.GozPerfParser = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const MAX_ROWS = 450000;
  const validNumber = (raw) => {
    if (raw === undefined || raw === null) return null;
    const s = String(raw).trim();
    if (!s || /^(NA|N\/A|null|nan|inf|infinity)$/i.test(s)) return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  };

  // Streaming-safe CSV tokenizer: commas/CRLF inside quotes and escaped quotation marks.
  function tokenize(csv) {
    const table = [];
    let row = [], cell = "", quoted = false;
    const source = String(csv || "").replace(/^\uFEFF/, "");
    for (let i = 0; i < source.length; i++) {
      const c = source[i];
      if (c === '"') {
        if (quoted && source[i + 1] === '"') { cell += '"'; i++; }
        else quoted = !quoted;
      } else if (c === "," && !quoted) {
        row.push(cell); cell = "";
      } else if ((c === "\n" || c === "\r") && !quoted) {
        if (c === "\r" && source[i + 1] === "\n") i++;
        row.push(cell); cell = "";
        if (row.some(x => x.trim())) table.push(row);
        row = [];
        if (table.length > MAX_ROWS + 1) throw new Error("CSV 超过 45 万行，请缩短录制时间后重试");
      } else cell += c;
    }
    if (quoted) throw new Error("CSV 引号未闭合，文件可能不完整");
    row.push(cell);
    if (row.some(x => x.trim())) table.push(row);
    return table;
  }

  function parse(text) {
    const raw = tokenize(text);
    if (!raw.length) throw new Error("CSV 文件为空");
    const headers = raw[0].map(v => v.trim().replace(/^\uFEFF/, ""));
    const required = ["MsBetweenDisplayChange", "MsBetweenPresents"];
    if (!required.some(s => headers.includes(s))) {
      throw new Error("未检测到 PresentMon 帧时间列。需要 MsBetweenDisplayChange 或 MsBetweenPresents；请确认是 PresentMon 的原始 CSV");
    }
    const known = ["Application","ProcessID","SwapChainAddress","FrameType","MsBetweenDisplayChange","MsBetweenPresents","DisplayedTime"];
    const index = Object.fromEntries(known.map(k => [k, headers.indexOf(k)]));
    const rows = [];
    for (const rawRow of raw.slice(1)) {
      if (!rawRow.some(x => x.trim())) continue;
      const obj = {};
      for (const k of known) obj[k] = index[k] >= 0 ? (rawRow[index[k]] || "").trim() : "";
      rows.push(obj);
    }
    if (!rows.length) throw new Error("CSV 没有数据行");
    const apps = [...new Set(rows.map(r => r.Application || "(未命名应用)"))].sort();
    return {headers, rows, apps};
  }

  function quantile(sorted, q) {
    if (!sorted.length) return null;
    const k = (sorted.length - 1) * q;
    const a = Math.floor(k), b = Math.ceil(k);
    return sorted[a] + (sorted[b] - sorted[a]) * (k - a);
  }

  // A game can create several swapchains; select its most active one to avoid
  // adding unrelated overlay/menu swapchain frames to FPS statistics.
  function summarize(parsed, appName) {
    const app = appName || parsed.apps[0];
    const selected = parsed.rows.filter(r => (r.Application || "(未命名应用)") === app);
    const displayed = selected.filter(r => {
      const n = validNumber(r.MsBetweenDisplayChange);
      return n !== null && n > 0 && n < 10000;
    });
    const preferred = displayed.length ? "MsBetweenDisplayChange" : "MsBetweenPresents";
    const eligible = preferred === "MsBetweenDisplayChange" ? displayed :
      selected.filter(r => { const n = validNumber(r.MsBetweenPresents); return n !== null && n > 0 && n < 10000; });
    const swapGroups = new Map();
    for (const r of eligible) {
      const name = r.SwapChainAddress || "(未提供)";
      if (!swapGroups.has(name)) swapGroups.set(name, []);
      swapGroups.get(name).push(r);
    }
    const mainGroup = [...swapGroups.entries()].sort((a,b) => b[1].length - a[1].length)[0];
    const main = mainGroup ? mainGroup[1] : [];
    const times = main.map(r => validNumber(r[preferred])).filter(n => n !== null && n > 0);
    if (!times.length) throw new Error("选择的游戏没有有效帧时间记录，可能使用了非受支持的渲染 API");
    const sorted = [...times].sort((a,b) => a - b);
    const avgMs = times.reduce((a,b) => a+b,0)/times.length;
    const q99 = quantile(sorted,0.99), q999 = quantile(sorted,0.999);
    const bySecond = [];
    let elapsed=0, sumMs=0, count=0, currentSecond=0;
    const finish = () => {
      if (count > 0) {
        bySecond.push({sec: currentSecond, fps: +(1000/(sumMs/count)).toFixed(1), frames:count});
      }
      sumMs=0; count=0;
    };
    for (const ms of times) {
      elapsed += ms;
      const next = Math.floor(elapsed/1000);
      if (next > currentSecond) { finish(); currentSecond=next; }
      sumMs += ms; count++;
    }
    finish();
    // PresentMon only reports FrameType on supported driver/app configurations.
    const frameTypes={};
    for (const r of main) {
      const k=(r.FrameType || "").trim();
      if (k && !/^(NA|N\/A)$/i.test(k)) frameTypes[k]=(frameTypes[k]||0)+1;
    }
    return {
      app, swapchain:mainGroup ? mainGroup[0] : "(无)", source:preferred,
      meanFps:+(1000/avgMs).toFixed(1),
      low1:+(1000/q99).toFixed(1),
      low01:+(1000/q999).toFixed(1),
      averageFrameMs:+avgMs.toFixed(2),
      p99FrameMs:+q99.toFixed(2),
      durationSec:+(elapsed/1000).toFixed(1),
      frames:times.length, rejected:Math.max(0,selected.length-times.length),
      chart:bySecond, frameTypes, fileProcessRows:selected.length,
      statsMethod:"P99/P99.9 帧时间倒数；与使用最慢 1% 帧均值的工具统计口径不同"
    };
  }

  return {parse, summarize, tokenize, quantile};
});
