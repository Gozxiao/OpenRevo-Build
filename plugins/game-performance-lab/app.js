/* UI uses only the browser File API and local CSV parser; no external network. */
(function () {
  "use strict";
  const parser = window.GozPerfParser;
  const $ = id => document.getElementById(id);
  const els = {
    input:$("input-csv"),app:$("app-select"),clear:$("clear"),export:$("export"),
    status:$("status"),root:$("dropzone"),chart:$("fps-chart"),empty:$("no-chart")
  };
  let model=null, summary=null, currentName="";
  function fmt(v,digits=1) { return typeof v==="number" && Number.isFinite(v) ? v.toFixed(digits) : "--"; }
  function status(msg,err=false) {
    els.status.textContent=msg;
    els.status.classList.toggle("error",!!err);
  }
  function writeText(id,text) { $(id).textContent=String(text); }
  function clearFields() {
    for (const id of ["avg-fps","low-1","low-01","frame-ms","count","detail-process","detail-duration","detail-p99","detail-source","detail-swap","detail-fg"]) writeText(id,"--");
    summary=null;
    els.export.disabled=true;
    els.empty.hidden=false;
    draw();
  }
  function draw() {
    const canvas=els.chart, rect=canvas.getBoundingClientRect();
    const w=Math.max(250,rect.width),h=Math.max(220,rect.height);
    const ratio=Math.min(2,window.devicePixelRatio||1);
    canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);
    const ctx=canvas.getContext("2d");ctx.scale(ratio,ratio);
    ctx.clearRect(0,0,w,h);
    if (!summary || !summary.chart || !summary.chart.length) return;
    els.empty.hidden=true;
    const pts=summary.chart;
    const left=43,right=w-18,top=15,bottom=h-28,plotW=right-left,plotH=bottom-top;
    const maxFps=Math.max(30,Math.ceil(Math.max(...pts.map(p=>p.fps))/30)*30);
    ctx.font="10px Segoe UI, Microsoft YaHei";ctx.textAlign="right";
    for (let i=0;i<=4;i++){
      const y=top+i*plotH/4,value=Math.round(maxFps*(4-i)/4);
      ctx.strokeStyle="#253449";ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();
      ctx.fillStyle="#7690a7";ctx.fillText(String(value),left-9,y+3);
    }
    const getX=i=>left+(pts.length===1?0:i/(pts.length-1)*plotW);
    const getY=p=>bottom-Math.max(0,Math.min(maxFps,p.fps))/maxFps*plotH;
    const step=Math.max(1,Math.ceil(pts.length/Math.max(2,plotW/5)));
    ctx.beginPath();
    for(let i=0;i<pts.length;i+=step){
      const x=getX(i),y=getY(pts[i]);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
    }
    const last=pts.length-1;
    if(last%step!==0)ctx.lineTo(getX(last),getY(pts[last]));
    ctx.lineTo(getX(last),bottom);ctx.lineTo(left,bottom);ctx.closePath();
    const grad=ctx.createLinearGradient(0,top,0,bottom);grad.addColorStop(0,"rgba(43,169,252,.32)");grad.addColorStop(1,"rgba(39,135,212,.02)");
    ctx.fillStyle=grad;ctx.fill();
    ctx.beginPath();
    for(let i=0;i<pts.length;i+=step){
      const x=getX(i),y=getY(pts[i]);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
    }
    if(last%step!==0)ctx.lineTo(getX(last),getY(pts[last]));
    ctx.strokeStyle="#40b9ff";ctx.lineWidth=2;ctx.stroke();
    ctx.fillStyle="#7f98b4";ctx.textAlign="center";ctx.font="10px Segoe UI, Microsoft YaHei";
    ctx.fillText("0s",left,bottom+17);
    ctx.fillText(Math.floor(summary.durationSec/2)+"s",left+plotW/2,bottom+17);
    ctx.fillText(Math.floor(summary.durationSec)+"s",right,bottom+17);
  }
  function display(app) {
    if(!model)return;
    try{
      summary=parser.summarize(model,app);
      writeText("avg-fps",fmt(summary.meanFps));
      writeText("low-1",fmt(summary.low1));
      writeText("low-01",fmt(summary.low01));
      writeText("frame-ms",fmt(summary.averageFrameMs,2));
      writeText("count",summary.frames.toLocaleString("zh-CN"));
      writeText("detail-process",summary.app);
      writeText("detail-duration",fmt(summary.durationSec)+" 秒");
      writeText("detail-p99",fmt(summary.p99FrameMs,2)+" ms");
      writeText("detail-source",summary.source);
      writeText("detail-swap",summary.swapchain);
      const types=Object.entries(summary.frameTypes);
      writeText("detail-fg",types.length?types.map(([t,n])=>t+": "+n).join(" / "):"源数据未提供 FrameType，不推断帧生成");
      status("已读取 "+currentName+" · "+summary.frames.toLocaleString("zh-CN")+" 个有效帧 · "+summary.rejected+" 行非主交换链/不可用记录已排除");
      els.export.disabled=false;draw();
    }catch(e){
      clearFields();
      status("分析失败："+(e && e.message?e.message:String(e)),true);
    }
  }
  async function openFile(file) {
    if(!file)return;
    if(file.size>85*1024*1024){status("CSV 超过 85 MB。为避免卡顿，请缩短录制时长后重试。",true);return;}
    if(!/\.csv$/i.test(file.name)){status("请导入 Intel PresentMon 导出的 .csv 文件。",true);return;}
    status("正在解析 "+file.name+"…");
    try{
      const bytes=await file.arrayBuffer();
      const u=new Uint8Array(bytes);
      const isUTF16=u.length>2 && u[0]===0xff && u[1]===0xfe;
      const text=new TextDecoder(isUTF16?"utf-16le":"utf-8").decode(u);
      const parsed=parser.parse(text);
      model=parsed;currentName=file.name;
      els.app.replaceChildren();
      for(const name of parsed.apps) {
        const option=document.createElement("option");option.value=name;option.textContent=name;els.app.appendChild(option);
      }
      els.app.disabled=parsed.apps.length<2;
      display(parsed.apps[0]);
    }catch(e){
      model=null;currentName="";clearFields();
      status("文件无法解析："+(e && e.message?e.message:String(e)),true);
    }
  }
  els.input.addEventListener("change",e=>{openFile(e.target.files && e.target.files[0]);});
  els.app.addEventListener("change",()=>display(els.app.value));
  els.clear.addEventListener("click",()=>{
    model=null;currentName="";els.input.value="";els.app.replaceChildren(new Option("尚未导入"));els.app.disabled=true;
    clearFields();status("记录已从当前窗口清除，没有保存到云端。");
  });
  els.export.addEventListener("click",()=>{
    if(!summary)return;
    const report={format:"gozxiao.openrevo.game-lab.report",version:1,exported_at:new Date().toISOString(),source_file:currentName,data:summary};
    const blob=new Blob([JSON.stringify(report,null,2)],{type:"application/json;charset=utf-8"});
    const url=URL.createObjectURL(blob);const a=document.createElement("a");
    a.href=url;a.download=("OpenRevo-"+summary.app.replace(/[^a-z0-9._-]/gi,"_")+"-report.json");
    document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  for(const event of ["dragenter","dragover"])els.root.addEventListener(event,e=>{e.preventDefault();els.root.classList.add("dragging");});
  for(const event of ["dragleave","drop"])els.root.addEventListener(event,e=>{e.preventDefault();els.root.classList.remove("dragging");});
  els.root.addEventListener("drop",e=>openFile(e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]));
  new ResizeObserver(draw).observe(els.chart.parentElement);
  draw();
})();