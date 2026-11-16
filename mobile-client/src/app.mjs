import {capabilities,prepare,exportMode} from './engine.mjs';
const $=id=>document.getElementById(id),files={},outputs=[],resultUrls=[];let controller=null,ready=false,changing=false;
function log(s){const line=new Date().toLocaleTimeString()+' '+s;$('log').textContent=($('log').textContent==='尚未开始'?'':$('log').textContent+'\n')+line;}
function status(s,error=false){$('progressBox').hidden=false;$('status').textContent=s;$('status').classList.toggle('error-text',error);log(s)}
function pick(host,key,label,accept,placeholder){
 const box=$(host),lab=document.createElement('label');lab.textContent=label;const row=document.createElement('div');row.className='pick';const name=document.createElement('span');name.textContent=placeholder||'未选择';name.id='fileLabel_'+key;const button=document.createElement('button');button.textContent='选择';const clear=document.createElement('button');clear.textContent='×';clear.className='quiet';clear.setAttribute('aria-label','清除'+label);clear.hidden=true;clear.id='clear_'+key;const input=document.createElement('input');input.type='file';input.accept=accept;input.hidden=true;input.id='file_'+key;input.setAttribute('aria-label',label);button.onclick=()=>input.click();input.onchange=()=>setFile(key,input.files[0]||null);clear.onclick=()=>{input.value='';setFile(key,null)};row.append(name,button,clear,input);box.append(lab,row);
}
function setFile(key,file){files[key]=file;const label=$('fileLabel_'+key);label.textContent=file?file.name+' · '+(file.size/1024/1024).toFixed(1)+'MB':'未选择';label.classList.toggle('selected',!!file);$('clear_'+key).hidden=!file;}
pick('bodyFile','body','正文视频','video/*','选择原视频 MP4 / MOV');pick('bodyVoice','voice','配音音频','audio/*','留空则保留视频全部原声');pick('bodySrt','srt','正文SRT','.srt','时间对应原画面，文字对应外语配音');pick('introFile','intro','片头视频','video/*');pick('musicFile','music','片头背景音乐（已去人声）','audio/*');pick('introVoice','introVoice','片头外语配音（可选）','audio/*');pick('introSrt','introSrt','片头SRT（自动同步时必选）','.srt');pick('outroFile','outro','片尾视频','video/*');pick('backgroundFile','background','竖版背景图（可选）','image/*');pick('landCover','coverLandscape','横版封面图（可选）','image/*');pick('portCover','coverPortrait','竖版封面图（可选）','image/*');
function ratio(){return document.querySelector('[name=ratio]:checked').value}
function update(){
 $('extend').disabled=$('autoSync').checked;$('syncHint').textContent=$('autoSync').checked?'SRT时间对应原视频画面；本机定位外语配音，逐句调整画面和字幕，保持配音原速。成片时长会随配音调整。':'自动同步已关闭：SRT须已准确对应当前配音；画面按原时间播放。';
 $('introSection').hidden=!$('introOn').checked;$('outroSection').hidden=!$('outroOn').checked;$('introReplacement').hidden=document.querySelector('[name=introMode]:checked').value!=='replace';
 const r=ratio();$('portraitOptions').hidden=r==='landscape';$('landStyle').hidden=r==='portrait';$('portStyle').hidden=r==='landscape';$('portCover').hidden=r==='landscape';$('landCover').hidden=r==='portrait';$('gainLabel').textContent=Math.round(Number($('musicGain').value)*100)+'%';
}
for(const e of document.querySelectorAll('input,select'))e.addEventListener('change',update);$('musicGain').addEventListener('input',update);update();
$('appearance').onclick=()=>$('settings').showModal();$('help').onclick=()=>$('instructions').showModal();for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>$(b.dataset.close).close();
function options(){
 const numeric=id=>{const n=Number($(id).value);if(!Number.isFinite(n))throw Error('请填写有效字号或位置');return n};
 return {introOn:$('introOn').checked,outroOn:$('outroOn').checked,introMode:document.querySelector('[name=introMode]:checked').value,ratio:ratio(),burn:$('burn').checked,autoSync:$('autoSync').checked,extend:$('extend').checked,quality:numeric('quality'),coverTime:numeric('coverTime'),musicGain:numeric('musicGain'),title:$('title').value,name:$('projectName').value,language:$('language').value,landFont:numeric('landFont'),portFont:numeric('portFont'),landY:numeric('landY'),portY:numeric('portY')};
}
function busy(on){for(const e of document.querySelectorAll('input,select,button')){if(e.id==='stop')continue;e.disabled=on}if(!on){$('run').disabled=!ready;$('smoke').disabled=!ready;$('preview').disabled=!ready;update()}$('stop').hidden=!on;$('run').hidden=on;}
function clearResults(){for(const u of resultUrls)URL.revokeObjectURL(u);resultUrls.length=0;outputs.length=0;$('resultList').replaceChildren();$('results').hidden=true;}
function showResult(result){
 outputs.push(result);const card=document.createElement('div');card.className='result-card';const h=document.createElement('h3');h.textContent=result.name;const desc=document.createElement('p');desc.className='hint';desc.textContent=result.width+'×'+result.height+' · '+result.duration.toFixed(2)+'秒 · '+(result.blob.size/1024/1024).toFixed(1)+'MB';
 const url=URL.createObjectURL(result.blob),srtUrl=URL.createObjectURL(result.srt);resultUrls.push(url,srtUrl);const video=document.createElement('video');video.controls=true;video.playsInline=true;video.preload='metadata';video.src=url;
 const save=document.createElement('a');save.href=url;save.download=result.name;save.textContent=result.isPreview?'下载20秒试听预览':'下载完整MP4';const srt=document.createElement('a');srt.href=srtUrl;srt.download=result.srtName;srt.textContent='保存SRT';const share=document.createElement('button');share.textContent='分享／保存到手机';share.onclick=async()=>{try{const f=new File([result.blob],result.name,{type:'video/mp4'});if(navigator.canShare?.({files:[f]}))await navigator.share({files:[f],title:result.name});else save.click()}catch(e){if(e.name!=='AbortError')status('系统分享未完成，可用下载链接保存。',true)}};
 card.append(h,desc,video,save,srt,document.createElement('br'),share);
 if(result.syncReport?.length){const report=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent='音画同步结果';pre.textContent=result.syncReport.map(r=>({intro:'片头',body:'正文'}[r.kind])+': '+r.sourceDuration.toFixed(2)+'秒画面 → '+r.duration.toFixed(2)+'秒；'+r.voiceCues.length+'句，匹配 '+Math.round(r.coverage*100)+'%；配音原速完整保留').join('\n');report.append(summary,pre);card.append(report)}$('resultList').append(card);$('results').hidden=false;
}
async function run(preview=false,test=null){
 if(controller||!ready)return;controller=new AbortController();busy(true);clearResults();$('progress').value=0;let plan=null,wake=null;
 try{
  try{wake=await navigator.wakeLock?.request('screen')}catch{}
  status('检查素材与SRT…');plan=await prepare(test?.files||{...files},{...(test?.options||options()),previewLimit:preview?20:0},controller.signal,s=>{log(s);$('status').textContent=s});
  log('完整顺序：'+plan.timelines[plan.modes[0]].segments.map(s=>({cover:'封面',intro:'片头',body:'正文',outro:'片尾'}[s.kind])).join(' → '));
  for(let i=0;i<plan.modes.length;i++){
   const mode=plan.modes[i];status('正在本机合成'+(mode==='portrait'?'竖版':'横版')+'，请保持页面在前台。');
   const result=await exportMode(plan,mode,controller.signal,p=>{$('progress').value=(i+p)/plan.modes.length;$('status').textContent='正在合成'+(mode==='portrait'?'竖版':'横版')+' '+Math.round(p*100)+'%'},log);showResult(result);
  }
  status(preview?'20秒试听／预览已完成。点“在手机上合成”可导出完整视频。':'完整视频合成完成。请先播放检查，再保存到手机。');$('results').scrollIntoView({behavior:'smooth',block:'start'});
 }catch(e){status(e.message||String(e),true);log('未把失败或中断的输出当作成片。已完成的另一个比例仍可保存。')}
 finally{plan?.dispose();await wake?.release().catch(()=>{});controller=null;busy(false)}
}
$('run').onclick=()=>run(false);$('preview').onclick=()=>run(true);$('stop').onclick=()=>{controller?.abort();status('正在停止并释放资源…')};
$('smoke').onclick=async()=>{
 if(controller||changing)return;changing=true;busy(true);let sample;
 try{
  status('准备6秒兼容样例，不改变你已选的素材和设置。');
  const load=async(name)=>{const r=await fetch('/samples/'+name);if(!r.ok)throw Error('样例加载失败');return new File([await r.blob()],name,{type:name.endsWith('.mp4')?'video/mp4':name.endsWith('.wav')?'audio/wav':'text/plain'})};
  const [intro,body,outro,voice,srt]=await Promise.all(['intro.mp4','body.mp4','outro.mp4','voice.wav','body.srt'].map(load));
  sample={files:{intro,body,outro,voice,srt},options:{...options(),introOn:true,outroOn:true,introMode:'original',autoSync:false,burn:true,extend:false,ratio:'portrait',quality:540,name:'本机兼容测试'}};
 }catch(e){status(e.message,true);changing=false;busy(false);return}
 changing=false;busy(false);await run(false,sample);
};
async function musicDB(mode,value){return new Promise((resolve,reject)=>{const q=indexedDB.open('yangning-mobile-music',1);q.onupgradeneeded=()=>q.result.createObjectStore('defaults');q.onerror=()=>reject(q.error);q.onsuccess=()=>{const db=q.result,t=db.transaction('defaults',mode==='get'?'readonly':'readwrite'),s=t.objectStore('defaults');let req;if(mode==='get')req=s.get('intro');if(mode==='set')req=s.put(value,'intro');if(mode==='clear')req=s.delete('intro');let result;req.onsuccess=()=>result=req.result;t.oncomplete=()=>{db.close();resolve(result)};t.onerror=()=>{db.close();reject(t.error)}}})}
$('rememberMusic').onclick=async()=>{try{if(!files.music)throw Error('请先选择片头背景音乐');if(files.music.size>30*1024*1024)throw Error('默认音乐请使用30MB以内的文件');await musicDB('set',files.music);status('已在本机记住片头音乐，下次打开自动带入。')}catch(e){status(e.message,true)}};
$('forgetMusic').onclick=async()=>{try{await musicDB('clear');setFile('music',null);status('已清除本机默认片头音乐。')}catch(e){status('未能清除浏览器保存的音乐：'+e.message,true)}};
musicDB('get').then(f=>{if(f)setFile('music',f)}).catch(()=>log('当前浏览器无法保存默认音乐，可每次手动选择。'));
window.addEventListener('beforeunload',e=>{if(controller){e.preventDefault();e.returnValue=''}});
capabilities().then(c=>{ready=c.ok;$('compat').textContent=c.message;$('compat').classList.toggle('error',!c.ok);$('run').disabled=!ready;$('smoke').disabled=!ready;$('preview').disabled=!ready;update()}).catch(e=>{$('compat').className='error';$('compat').textContent='本机能力检查失败：'+e.message});
