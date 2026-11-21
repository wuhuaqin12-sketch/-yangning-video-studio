import {pipeline,env} from '@huggingface/transformers';
import {japaneseReadings} from './japanese-reading.mjs';
import {MODEL} from './sync.mjs';
env.allowLocalModels=false;env.useBrowserCache=true;
env.backends.onnx.wasm.numThreads=1;env.backends.onnx.wasm.wasmPaths='/onnx/';
let recognizer;
self.onmessage=async({data})=>{
 try{
  if(!recognizer){const seen=new Map();recognizer=await pipeline('automatic-speech-recognition',MODEL.id,{revision:MODEL.revision,dtype:MODEL.dtype,device:'wasm',progress_callback:p=>{if(p.status==='progress'){const value=Math.floor(p.progress/10)*10;if(seen.get(p.file)!==value){seen.set(p.file,value);self.postMessage({type:'progress',text:'下载本机定位模型 · '+p.file.split('/').at(-1)+' '+value+'%'})}}}})}
  self.postMessage({type:'progress',text:'在本机识别配音中的词语和时间，请保持页面在前台…'});
  const result=await recognizer(data.audio,{language:data.language,task:'transcribe',return_timestamps:'word',chunk_length_s:30,stride_length_s:5});
  if(data.language==='japanese'){self.postMessage({type:'progress',text:'在本机核对日语读音，区分同音汉字与漏句…'});result.readings=await japaneseReadings(result,data.references)}
  self.postMessage({type:'result',result});
 }catch(e){self.postMessage({type:'error',message:e.message||String(e)})}
};
