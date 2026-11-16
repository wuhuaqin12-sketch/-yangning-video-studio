import {capabilities,prepare,exportMode} from './engine.mjs';
const $=id=>document.getElementById(id);let controller;
const log=s=>{$('log').textContent+=s+'\n';$('status').textContent=s};
function link(blob,name){const a=document.createElement('a');a.download=name;a.href=URL.createObjectURL(blob);a.textContent=name;a.style.display='block';$('results').append(a)}
$('start').onclick=async()=>{let plan;controller=new AbortController();$('start').disabled=true;try{
 if(!(await capabilities()).ok)throw Error('本机视频编码不可用');
 const file=async(name,root='/sync-test-data/')=>{const r=await fetch(root+name);if(!r.ok)throw Error('验收素材未加载');return new File([await r.blob()],name,{type:name.endsWith('.mp4')?'video/mp4':name.endsWith('.wav')?'audio/wav':name.endsWith('.png')?'image/png':'text/plain'})};
 const [body,voice,srt,intro,outro,coverLandscape,coverPortrait]=await Promise.all([file('source.mp4'),file('voice.wav'),file('source.srt'),file('intro.mp4','/samples/'),file('outro.mp4','/samples/'),file('cover_landscape.png','/samples/'),file('cover_portrait.png','/samples/')]);
 plan=await prepare({body,voice,srt,intro,outro,coverLandscape,coverPortrait},{introOn:true,outroOn:true,introMode:'original',autoSync:true,ratio:'both',burn:true,extend:false,quality:540,coverTime:3,musicGain:.35,title:'同期検証',name:'本机逐句同步验收',language:'日语',landFont:64,portFont:70,landY:0,portY:0},controller.signal,log);
 const report=plan.segments.filter(s=>s.syncReport).map(s=>({kind:s.kind,...s.syncReport}));
 $('report').textContent=JSON.stringify(report,null,2);link(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}),'sync-report.json');
 for(const mode of plan.modes){const r=await exportMode(plan,mode,controller.signal,p=>$('status').textContent=mode+' '+Math.round(p*100)+'%',log);link(r.blob,r.name);link(r.srt,r.srtName)}
 plan.options.previewLimit=20;const preview=await exportMode(plan,'landscape',controller.signal,p=>$('status').textContent='20秒预览 '+Math.round(p*100)+'%',log);link(preview.blob,preview.name);
 $('status').textContent='逐句音画同步已导出：两个完整版本＋20秒试听预览';
 }catch(e){log('失败：'+e.message);$('report').textContent=(e.diagnostic||'')+'\n'+e.stack}finally{plan?.dispose();$('start').disabled=false;controller=null}};
$('stop').onclick=()=>controller?.abort();
