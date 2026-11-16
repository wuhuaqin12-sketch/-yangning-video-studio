import {MODEL,LANGUAGE,alignReference} from './sync.mjs';
function cache(mode,key,value){return new Promise((resolve,reject)=>{
 const q=indexedDB.open('yangning-local-alignment',1);q.onupgradeneeded=()=>q.result.createObjectStore('results');q.onerror=()=>reject(q.error);
 q.onsuccess=()=>{const db=q.result,t=db.transaction('results',mode==='get'?'readonly':'readwrite'),s=t.objectStore('results');let answer;const req=mode==='get'?s.get(key):s.put(value,key);req.onsuccess=()=>answer=req.result;t.oncomplete=()=>{db.close();resolve(answer)};t.onerror=()=>{db.close();reject(t.error)}}
})}
async function keyFor(file,language){const hash=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());return MODEL.id+'@'+MODEL.revision+'/'+language+'/'+Array.from(new Uint8Array(hash),n=>n.toString(16).padStart(2,'0')).join('')}
export class AlignmentSession{
 constructor(signal,log){this.signal=signal;this.log=log;this.worker=null}
 close(){this.worker?.terminate();this.worker=null}
 async align(source,sourceCues,pcm,duration,languageLabel){
  const language=LANGUAGE[languageLabel];if(!language)throw Error('本机自动音画同步暂未验证'+languageLabel+'。请关闭自动同步并使用已校对的配音SRT；不会改用其他语言识别。');
  if(this.signal?.aborted)throw Error('已停止配音定位。');
  let key=null,result=null;
  try{key=await keyFor(source.file,language)+'/'+await keyFor(new Blob([sourceCues.map(c=>c.text).join('\n')]),language);result=await cache('get',key)}catch{this.log('定位缓存不可用，本次仍可正常处理。')}
  if(result)this.log('复用本机配音定位结果，重新核对本次SRT。');
  else{
   if(this.signal?.aborted)throw Error('已停止配音定位。');
   this.log('首次需下载约77MB模型及本机运行组件，不上传素材。');
   if(!this.worker)this.worker=new Worker(new URL('/alignment-worker.js?v=0.2.0',location.origin),{type:'module'});
   result=await new Promise((resolve,reject)=>{
    const worker=this.worker,abort=()=>{this.close();reject(Error('已停止配音定位。'))};
    const finish=(error,value)=>{this.signal?.removeEventListener('abort',abort);worker.onmessage=null;worker.onerror=null;error?reject(error):resolve(value)};
    worker.onmessage=({data})=>{if(data.type==='progress')this.log(data.text);else if(data.type==='result')finish(null,data.result);else if(data.type==='error')finish(Error('本机配音定位失败：'+data.message+'。可重试；不会切换到云端。'))};
    worker.onerror=e=>finish(Error('本机定位引擎未能运行：'+e.message));
    this.signal?.addEventListener('abort',abort,{once:true});
    worker.postMessage({audio:pcm,language,references:sourceCues.map(c=>c.text)},[pcm.buffer]);
   });
   if(key)try{await cache('set',key,result)}catch{}
  }
  if(this.signal?.aborted)throw Error('已停止配音定位。');
  let aligned;
  try{aligned=alignReference(sourceCues,result.chunks,duration)}catch(e){
   if(language==='japanese'&&result.readings){
    try{const phonetic=sourceCues.map((c,i)=>({...c,text:result.readings.references[i]}));aligned=alignReference(phonetic,result.readings.chunks,duration,{minCoverage:.82,minPrecision:.78,minCue:.75});aligned.cues=aligned.cues.map((c,i)=>({...c,text:sourceCues[i].text}));aligned.method='日语读音核对';this.log('日语汉字写法不同，已通过读音逐句核对，保留SRT原文。')}
    catch(readingError){readingError.diagnostic=JSON.stringify(result,null,2);throw readingError}
   }else{e.diagnostic=JSON.stringify(result,null,2);throw e}
  }
  this.log('逐句定位完成：'+aligned.cues.length+'句；参考稿匹配 '+Math.round(aligned.coverage*100)+'%。'+(aligned.corrections?'已约束末字的小幅尾部越界。':''));
  return aligned;
 }
}
