const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const parser=require('../plugins/game-performance-lab/parse.js');
const manifest=require('../plugins/game-performance-lab/manifest.json');

const data=[
  'Application,ProcessID,SwapChainAddress,FrameType,MsBetweenDisplayChange,MsBetweenPresents,DisplayedTime',
  'game.exe,123,0xA,Application,16,16,16',
  'game.exe,123,0xA,Application,16,16,16',
  'game.exe,123,0xA,Application,20,20,20',
  'game.exe,123,0xA,Generated,16,16,16',
  'game.exe,123,0xA,Generated,16,16,16',
  'game.exe,123,0xB,Application,200,200,200',
  'other.exe,432,0xC,Application,33,33,33',
].join('\n');

test('OpenRevo plugin manifest has a valid tab entry and no hardware controls',()=>{
  assert.equal(manifest.plugin_type,'tab');
  assert.equal(manifest.entry,'index.html');
  assert.deepEqual(manifest.permissions,[]);
  assert.equal(manifest.telemetry.enabled,false);
  const root=path.join(__dirname,'../plugins/game-performance-lab');
  for(const f of ['index.html','app.js','parse.js','style.css','capture.cmd','run-capture.ps1'])
    assert.equal(fs.existsSync(path.join(root,f)),true,f);
});

test('PresentMon tokenizer handles quoted process names and CRLF',()=>{
  const rows=parser.tokenize('\uFEFFApplication,MsBetweenPresents\r\n"game, special.exe",16.7\r\n');
  assert.equal(rows[0][0],'Application');
  assert.equal(rows[1][0],'game, special.exe');
  assert.equal(rows[1][1],'16.7');
});

test('CSV summary chooses dominant swapchain and reports real percentile values',()=>{
  const parsed=parser.parse(data);
  assert.deepEqual(parsed.apps,['game.exe','other.exe']);
  const s=parser.summarize(parsed,'game.exe');
  assert.equal(s.swapchain,'0xA');
  assert.equal(s.frames,5);
  assert.equal(s.rejected,1);
  assert.ok(s.meanFps>55 && s.meanFps<65,s.meanFps);
  assert.ok(s.low1>45 && s.low1<65,s.low1);
  assert.equal(s.frameTypes.Generated,2);
  assert.equal(s.frameTypes.Application,3);
  assert.ok(s.chart.length>=1);
});

test('Fallback to MsBetweenPresents when display timing is unavailable',()=>{
  const parsed=parser.parse('Application,MsBetweenPresents,MsBetweenDisplayChange\nhello.exe,10,NA\nhello.exe,20,\n');
  const s=parser.summarize(parsed,'hello.exe');
  assert.equal(s.source,'MsBetweenPresents');
  assert.equal(s.meanFps,66.7);
});

test('Never invent FrameType or valid FPS from empty telemetry',()=>{
  const parsed=parser.parse('Application,MsBetweenDisplayChange,FrameType\nx.exe,NA,\nx.exe,0,NA\n');
  assert.throws(()=>parser.summarize(parsed),/没有有效帧时间/);
  assert.throws(()=>parser.parse('nothing,here\nx,y'),/未检测到 PresentMon/);
});

test('Quantiles are monotonic and 1% Low <= average FPS for slowdown frames',()=>{
  const rows=['Application,MsBetweenDisplayChange'];
  for(let i=0;i<100;i++)rows.push('game.exe,'+(i>=98?'100':'10'));
  const s=parser.summarize(parser.parse(rows.join('\n')));
  assert.ok(s.low1<s.meanFps,{low:s.low1,mean:s.meanFps});
  assert.ok(s.low01<=s.low1);
});

test('No external scripts or hardware write APIs in plugin frontend',()=>{
  const root=path.join(__dirname,'../plugins/game-performance-lab');
  const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
  const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
  assert.doesNotMatch(html,/<script[^>]+https?:\/\//);
  assert.doesNotMatch(app,/set_water_cooler|set_fan_boost|set_gpu_mode|https?:\/\/\S+\/api/i);
});
