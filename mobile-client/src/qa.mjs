import {capabilities,prepare,exportMode} from './engine.mjs';
const $=id=>document.getElementById(id),log=t=>$('qa-log').textContent+=t+'\n';
$('qa-run').onclick=async()=>{let plan=null;try{$('qa-run').disabled=true;if(!(await capabilities()).ok)throw Error('本机编码不可用');
 const file=async name=>{const r=await fetch('/samples/'+name);return new File([await r.blob()],name,{type:name.endsWith('.png')?'image/png':name.endsWith('.mp4')?'video/mp4':name.endsWith('.wav')?'audio/wav':'text/plain'})};
 const names={body:'body20.mp4',voice:'voice20.wav',srt:'body.srt',intro:'intro.mp4',music:'music2.wav',introVoice:'intro_voice2.wav',introSrt:'body.srt',outro:'outro.mp4',coverLandscape:'cover_landscape.png',coverPortrait:'cover_portrait.png',background:'background.png'};
 const files=Object.fromEntries(await Promise.all(Object.entries(names).map(async([key,name])=>[key,await file(name)])));
 plan=await prepare(files,{introOn:true,outroOn:true,introMode:'replace',ratio:'both',burn:true,extend:false,quality:540,coverTime:3,musicGain:.35,title:'金剛経',name:'综合验收',language:'日语',landFont:64,portFont:70,landY:0,portY:0},null,log);
 for(const mode of plan.modes){const result=await exportMode(plan,mode,null,p=>$('qa-status').textContent=mode+' '+Math.round(p*100)+'%',log);const link=document.createElement('a');link.download=result.name;link.href=URL.createObjectURL(result.blob);link.textContent=result.name+' '+result.duration.toFixed(2)+'秒';link.style.display='block';$('qa-results').append(link);const srt=document.createElement('a');srt.download=result.srtName;srt.href=URL.createObjectURL(result.srt);srt.textContent=result.srtName;srt.style.display='block';$('qa-results').append(srt)}
 $('qa-status').textContent='综合验收完成：两个27秒MP4已导出';
 }catch(e){$('qa-status').textContent='失败：'+e.message;log(e.stack)}finally{plan?.dispose();$('qa-run').disabled=false}};
