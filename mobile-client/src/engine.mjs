import {Input,ALL_FORMATS,BlobSource,AudioBufferSink,CanvasSink,Output,Mp4OutputFormat,BufferTarget,CanvasSource,AudioBufferSource,Quality,canEncodeVideo,canEncodeAudio} from 'mediabunny';
import {registerAacEncoder} from '@mediabunny/aac-encoder';
import {AlignmentSession} from './alignment.mjs';
import {pictureTimeline,sourceTimeAt} from './sync.mjs';
import {parseSrt,segmentLength,makeTimeline,combinedCues,srtText,fitRect,pageAt,safeName} from './core.mjs';
const SR=48000,FPS=24;
export class Cancelled extends Error{constructor(){super('已停止处理，原素材未改变。')}}
function check(signal){if(signal?.aborted)throw new Cancelled()}
export async function capabilities(){
 if(!globalThis.isSecureContext)return {ok:false,message:'请通过安全的HTTPS网页打开手机版。'};
 if(!globalThis.VideoEncoder||!globalThis.VideoDecoder)return {ok:false,message:'当前浏览器缺少本机视频编码／解码能力。请使用支持WebCodecs的新版系统浏览器。'};
 let aac=await canEncodeAudio('aac',{numberOfChannels:2,sampleRate:SR});
 if(!aac){registerAacEncoder();aac=await canEncodeAudio('aac',{numberOfChannels:2,sampleRate:SR})}
 const avc=await canEncodeVideo('avc',{width:540,height:960,frameRate:FPS,quality:new Quality({bitrate:2000000})});
 return {ok:avc&&aac,message:avc&&aac?'本机支持MP4合成。建议先运行6秒样例。':'当前浏览器不能输出所需的H.264＋AAC MP4，已暂停合成功能。'};
}
async function media(file,video,inputs){
 if(!file)throw Error(video?'请选择视频文件':'请选择音频文件');
 const input=new Input({source:new BlobSource(file),formats:ALL_FORMATS});inputs.push(input);
 const track=video?await input.getPrimaryVideoTrack():await input.getPrimaryAudioTrack();
 if(!track)throw Error(file.name+'没有可用的'+(video?'画面':'音轨'));
 if(!await track.canDecode())throw Error(file.name+'的'+(video?'视频':'音频')+'编码不被本机支持，请换用H.264 MP4或AAC/WAV音频。');
 const start=Math.max(0,await track.getFirstTimestamp()),end=await track.computeDuration();
 if(!(end>start))throw Error(file.name+'没有有效时长');
 if(end-start>600)throw Error(file.name+'超过本版10分钟处理上限。');
 return {file,input,track,start,duration:end-start};
}
async function image(file){
 if(!file)return null;
 if(!file.type.startsWith('image/'))throw Error(file.name+'不是图片，请重新选择封面或背景。');
 try{return await createImageBitmap(file)}catch{
  const url=URL.createObjectURL(file);try{const im=new Image();im.src=url;await im.decode();return im}finally{URL.revokeObjectURL(url)}
 }
}
async function cues(file,duration,label){
 const data=file?parseSrt(await file.text()):[];
 if(data.some(c=>c.end>duration+.08))throw Error(label+'SRT超过该段画面／配音时长。请检查该SRT属于原视频还是当前配音，并选择对应的同步方式；不会截断素材。');
 return data;
}
export async function prepare(files,options,signal,log){
 const inputs=[],images=[],aligner=new AlignmentSession(signal,log);
 try{
  const all=Object.values(files).filter(x=>x instanceof Blob);if(all.reduce((s,f)=>s+f.size,0)>300*1024*1024)throw Error('素材合计超过本版300MB上限，请先用较小片段测试。');
  const segments=[];
  const add=async(kind,videoFile,voiceFile,srtFile)=>{
   check(signal);log('检查'+({intro:'片头',body:'正文',outro:'片尾'}[kind])+'素材…');
   const v=await media(videoFile,true,inputs),voice=voiceFile?await media(voiceFile,false,inputs):null;
   const originalAudio=await v.input.getPrimaryAudioTrack();
   let audio=null;if(!voice&&originalAudio){if(!await originalAudio.canDecode())throw Error(videoFile.name+'原音轨无法解码');audio={input:v.input,track:originalAudio,start:v.start,duration:Math.max(0,await originalAudio.computeDuration()-v.start)}}
   const label=kind==='body'?'正文':'片头';
   let seg;
   if(voice&&options.autoSync){
    if(!srtFile)throw Error(label+'自动音画同步需要SRT，其时间应对应这段原视频画面。');
    const original=await cues(srtFile,v.duration,label);
    if(!original.length)throw Error(label+'SRT为空，无法进行逐句音画同步。');
    log('定位'+label+'配音：逐句对照原画面SRT…');
    const located=await aligner.align(voice,original,await decodeSpeech(voice,signal),voice.duration,options.language);
    const mapped=pictureTimeline(original,located.cues,v.duration,voice.duration,FPS);
    seg={kind,video:v,voice,audio:null,duration:mapped.duration,cues:mapped.cues,mapping:mapped.points,voiceOffset:mapped.voiceOffset,syncReport:{coverage:located.coverage,scores:located.scores,corrections:located.corrections,sourceDuration:v.duration,voiceDuration:voice.duration,duration:mapped.duration,voiceOffset:mapped.voiceOffset,sourceCues:original,voiceCues:located.cues,points:mapped.points}};
    log(label+'画面按每句配音调整：'+v.duration.toFixed(2)+'秒 → '+mapped.duration.toFixed(2)+'秒；配音保持原速。');
   }else{
    const duration=segmentLength(v.duration,voice?.duration||audio?.duration||0,options.extend);
    seg={kind,video:v,voice,audio,duration,cues:await cues(srtFile,duration,label)};
   }
   segments.push(seg);return seg;
  };
  if(options.introOn){
   if(options.introMode==='replace'){
    if(!files.music)throw Error('替换片头声音时，请选择已去人声的片头背景音乐。');
    const seg=await add('intro',files.intro,files.introVoice,files.introSrt);
    if(!seg.voice)seg.audio=null;
    seg.music=await media(files.music,false,inputs);seg.replace=true;
    if(seg.music.duration+.05<seg.duration)throw Error('片头背景音乐短于完整片头；不会自动循环或截断片头。');
   }else await add('intro',files.intro,null,null);
  }
  await add('body',files.body,files.voice,files.srt);
  if(options.outroOn)await add('outro',files.outro,null,null);
  const modes=options.ratio==='both'?['landscape','portrait']:[options.ratio];
  const covers={};for(const mode of modes){covers[mode]=await image(files[mode==='portrait'?'coverPortrait':'coverLandscape']);if(covers[mode])images.push(covers[mode])}
  const background=modes.includes('portrait')?await image(files.background):null;if(background)images.push(background);
  const timelines={};for(const mode of modes){timelines[mode]=makeTimeline(segments,covers[mode]?options.coverTime:0);if(timelines[mode].duration>600)throw Error('完整成片超过本版10分钟上限，请分段处理。')}
  check(signal);return {segments,modes,covers,background,timelines,options,dispose(){inputs.forEach(i=>i.dispose());images.forEach(i=>i.close?.())}};
 }catch(e){inputs.forEach(i=>i.dispose());images.forEach(i=>i.close?.());throw e}finally{aligner.close()}
}
async function decodeSpeech(source,signal){
 const rate=16000,data=new Float32Array(Math.ceil(source.duration*rate)),sink=new AudioBufferSink(source.track);
 for await(const {buffer,timestamp} of sink.buffers(source.start,source.start+source.duration)){
  check(signal);const t0=timestamp-source.start,a=Math.max(0,Math.ceil(t0*rate)),b=Math.min(data.length,Math.ceil((t0+buffer.duration)*rate));
  const channels=Array.from({length:buffer.numberOfChannels},(_,i)=>buffer.getChannelData(i));
  for(let k=a;k<b;k++){const at=(k/rate-t0)*buffer.sampleRate,i=Math.max(0,Math.min(buffer.length-1,Math.floor(at))),f=Math.max(0,Math.min(1,at-i));let v=0;for(const ch of channels)v+=ch[i]*(1-f)+ch[Math.min(i+1,ch.length-1)]*f;data[k]=v/channels.length}
 }
 return data;
}
async function decodeAudio(source,duration,signal){
 const data=[new Float32Array(Math.ceil(duration*SR)),new Float32Array(Math.ceil(duration*SR))];
 if(!source)return data;
 if(source.track.numberOfChannels>2)throw Error(source.file?.name+'音轨超过2声道，本版暂不自动降混。');
 const sink=new AudioBufferSink(source.track);
 for await(const {buffer,timestamp} of sink.buffers(source.start,source.start+duration)){
  check(signal);const t0=timestamp-source.start,a=Math.max(0,Math.ceil(t0*SR)),b=Math.min(data[0].length,Math.ceil((t0+buffer.duration)*SR));
  for(let ch=0;ch<2;ch++){
   const src=buffer.getChannelData(Math.min(ch,buffer.numberOfChannels-1)),dst=data[ch];
   for(let k=a;k<b;k++){const at=(k/SR-t0)*buffer.sampleRate,i=Math.max(0,Math.min(src.length-1,Math.floor(at))),f=Math.max(0,Math.min(1,at-i));dst[k]=src[i]*(1-f)+src[Math.min(i+1,src.length-1)]*f}
  }
 }
 return data;
}
async function segmentAudio(seg,signal,log,gain){
 let pcm;
 if(seg.voice&&seg.mapping){
  const raw=await decodeAudio(seg.voice,seg.voice.duration,signal),length=Math.ceil(seg.duration*SR),offset=Math.round(seg.voiceOffset*SR);
  pcm=[new Float32Array(length),new Float32Array(length)];if(offset<length)for(let c=0;c<2;c++)pcm[c].set(raw[c].subarray(0,length-offset),offset);
 }else pcm=await decodeAudio(seg.voice||seg.audio,seg.duration,signal);
 if(seg.music){const music=await decodeAudio(seg.music,seg.duration,signal);for(let c=0;c<2;c++)for(let i=0;i<pcm[c].length;i++)pcm[c][i]+=music[c][i]*gain;}
 let peak=0;for(const ch of pcm)for(const n of ch)peak=Math.max(peak,Math.abs(n));
 if(peak>.98){const factor=.98/peak;for(const ch of pcm)for(let i=0;i<ch.length;i++)ch[i]*=factor;log('混音峰值过高，整体衰减'+(-20*Math.log10(factor)).toFixed(1)+'dB以避免削波。')}
 return pcm;
}
function dimensions(mode,quality){return mode==='portrait'?[quality,Math.round(quality*16/9/2)*2]:[Math.round(quality*16/9/2)*2,quality]}
function baseFrame(ctx,W,H,frame,mode,kind,plan){
 ctx.fillStyle='#101010';ctx.fillRect(0,0,W,H);
 if(kind==='cover'){const box=fitRect(frame.width,frame.height,0,0,W,H);ctx.drawImage(frame,box.x,box.y,box.w,box.h);return null}
 if(mode==='portrait'&&plan.background){const bg=plan.background,scale=Math.max(W/bg.width,H/bg.height);ctx.drawImage(bg,(W-bg.width*scale)/2,(H-bg.height*scale)/2,bg.width*scale,bg.height*scale)}
 const box=mode==='landscape'?fitRect(frame.width,frame.height,0,0,W,H):fitRect(frame.width,frame.height,0,H*.18,W,H*.64);
 ctx.drawImage(frame,box.x,box.y,box.w,box.h);
 if(mode==='portrait'&&kind==='body'&&plan.options.title){
  const title=plan.options.title;let size=W*.09;ctx.font='600 '+size+'px serif';while(ctx.measureText(title).width>W*.9&&size>14){size--;ctx.font='600 '+size+'px serif'}
  ctx.fillStyle='#f0d17c';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(title,W/2,box.y*.55);
 }
 return box;
}
function drawCaptions(ctx,W,H,seg,t,mode,box,options){
 if(!options.burn||!seg.cues?.length||seg.kind==='outro')return;
 const cue=seg.cues.find(c=>t>=c.start&&t<c.end);if(!cue)return;
 const scale=mode==='portrait'?W/1080:H/1080,font=(mode==='portrait'?options.portFont:options.landFont)*scale,offset=(mode==='portrait'?options.portY:options.landY)*scale;
 if(!Number.isFinite(font)||font<4)throw Error('请填写有效字幕字号。');
 const line=font*1.3,safe=H*.025;
 let y=mode==='portrait'?box.y+box.h+font*.7+offset:H*.80+offset;
 y=Math.max(safe,Math.min(H-safe-line,y));const count=Math.min(5,Math.floor((H-safe-y)/line));
 if(count<1)throw Error('字号或位置超出画面，请调小字号或上移字幕。');
 ctx.font='600 '+font+'px serif';ctx.textAlign='center';ctx.textBaseline='top';ctx.lineWidth=Math.max(1.5,font*.07);ctx.lineJoin='round';
 const lines=pageAt(cue.text,t,cue.start,cue.end,s=>ctx.measureText(s).width,W*.9,count);
 for(let i=0;i<lines.length;i++){ctx.strokeStyle='#171717';ctx.fillStyle='white';ctx.strokeText(lines[i],W/2,y+i*line);ctx.fillText(lines[i],W/2,y+i*line)}
}
export async function exportMode(plan,mode,signal,progress,log){
 const [W,H]=dimensions(mode,plan.options.quality);let timeline=plan.timelines[mode];
 if(plan.options.previewLimit&&timeline.duration>plan.options.previewLimit){const limit=plan.options.previewLimit;timeline={duration:limit,segments:timeline.segments.filter(s=>s.start<limit).map(s=>({...s,duration:Math.min(s.duration,limit-s.start),end:Math.min(s.end,limit),cues:(s.cues||[]).filter(c=>c.start<limit-s.start).map(c=>({...c,end:Math.min(c.end,limit-s.start)}))}))}}
 if(!await canEncodeVideo('avc',{width:W,height:H,frameRate:FPS,quality:new Quality({bitrate:plan.options.quality===720?4000000:2500000})}))throw Error('本机不支持所选尺寸的H.264编码，请选择540p或换兼容浏览器。');
 const canvas=document.createElement('canvas');canvas.width=W;canvas.height=H;const ctx=canvas.getContext('2d',{alpha:false});
 const output=new Output({format:new Mp4OutputFormat({fastStart:'in-memory'}),target:new BufferTarget()});
 const video=new CanvasSource(canvas,{codec:'avc',quality:new Quality({bitrate:plan.options.quality===720?4000000:2500000}),keyFrameInterval:2,latencyMode:'quality'});
 const audio=new AudioBufferSource({codec:'aac',quality:new Quality({bitrate:160000})});
 output.addVideoTrack(video,{frameRate:FPS});output.addAudioTrack(audio);await output.start();
 const abort=()=>{output.cancel().catch(()=>{})};signal?.addEventListener('abort',abort,{once:true});
 let totalFrames=0;
 try{
  for(const seg of timeline.segments){
   check(signal);log('合成'+({cover:'封面',intro:'片头',body:'正文',outro:'片尾'}[seg.kind])+' · '+(mode==='portrait'?'竖版':'横版'));
   const frames=Math.round(seg.duration*FPS),pcm=seg.kind==='cover'?null:await segmentAudio(seg,signal,log,plan.options.musicGain);
   let iterator=null;
   if(seg.kind!=='cover'){
    const source=seg.video;const sink=new CanvasSink(source.track,{width:W,fit:'contain',poolSize:1});
    function* times(){for(let n=0;n<frames;n++)yield source.start+Math.min(sourceTimeAt(seg.mapping,n/FPS),Math.max(0,source.duration-1/FPS))}
    iterator=sink.canvasesAtTimestamps(times());
   }
   try{
    for(let n=0;n<frames;n++){
     check(signal);
     if(n%FPS===0){
      const length=Math.min(FPS,frames-n)*SR/FPS,buffer=new AudioBuffer({numberOfChannels:2,length,sampleRate:SR});
      if(pcm)for(let ch=0;ch<2;ch++)buffer.copyToChannel(pcm[ch].subarray(n*SR/FPS,n*SR/FPS+length),ch);
      await audio.add(buffer);
     }
     let frame=plan.covers[mode];
     if(iterator){const next=await iterator.next();if(!next.value)throw Error('未能解码第'+(n+1)+'帧，已停止生成。');frame=next.value.canvas;}
     const box=baseFrame(ctx,W,H,frame,mode,seg.kind,plan);
     if(box)drawCaptions(ctx,W,H,seg,n/FPS,mode,box,plan.options);
     await video.add(totalFrames/FPS,1/FPS);totalFrames++;
     if(n%12===0){progress(totalFrames/FPS/timeline.duration);await new Promise(r=>setTimeout(r,0))}
    }
   }finally{await iterator?.return?.()}
  }
  video.close();audio.close();check(signal);await output.finalize();check(signal);progress(1);
  const blob=new Blob([output.target.buffer],{type:'video/mp4'});if(blob.size<1000)throw Error('导出文件不完整。');
  const fileName=safeName(plan.options.name)+'_'+safeName(plan.options.language)+(plan.options.previewLimit?'_20秒试听预览':'')+'_'+(mode==='portrait'?'竖版_9x16':'横版_16x9');
  return {blob,isPreview:!!plan.options.previewLimit,name:fileName+'.mp4',srt:new Blob(['\uFEFF'+srtText(combinedCues(timeline))],{type:'application/x-subrip;charset=utf-8'}),srtName:fileName+'.srt',duration:timeline.duration,width:W,height:H,syncReport:timeline.segments.filter(s=>s.syncReport).map(s=>({kind:s.kind,start:s.start,...s.syncReport}))};
 }catch(e){if(output.state!=='canceled'&&output.state!=='finalized')await output.cancel().catch(()=>{});if(signal?.aborted)throw new Cancelled();throw e}
 finally{signal?.removeEventListener('abort',abort)}
}
