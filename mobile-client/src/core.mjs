export function parseSrt(text){
 const blocks=text.replace(/^\uFEFF/,'').replace(/\r/g,'').trim().split(/\n\s*\n/),cues=[];
 if(!text.trim())return [];
 const stamp=s=>{const m=s.match(/^(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})$/);if(!m||+m[2]>59||+m[3]>59)throw Error('SRT时间格式不正确');return +m[1]*3600 + +m[2]*60 + +m[3] + +m[4]/1000};
 for(const [i,b] of blocks.entries()){
  const lines=b.split('\n');if(/^\d+$/.test(lines[0].trim()))lines.shift();
  const m=lines.shift()?.trim().match(/^(\S+)\s*-->\s*(\S+)\s*$/);if(!m)throw Error('SRT第'+(i+1)+'段缺少正确时间轴');
  const start=stamp(m[1]),end=stamp(m[2]),body=lines.join('\n').replace(/<[^>]*>/g,'').trim();
  if(end<=start||!body)throw Error('SRT第'+(i+1)+'段时间或文字为空');
  if(cues.length&&start<cues.at(-1).end-.001)throw Error('SRT第'+(i+1)+'段与上一段重叠，请先校对时间轴');
  cues.push({start,end,text:body});
 }
 return cues;
}
export const quantize=(s,fps=24)=>Math.ceil(s*fps-1e-6)/fps;
export function segmentLength(video,audio,extend){
 if(!(video>0)||!Number.isFinite(video))throw Error('未读到有效的视频时长');
 if(audio>video+.08&&!extend)throw Error('配音比画面长约'+(audio-video).toFixed(1)+'秒。请启用“延长末帧”或另准备匹配的素材；不会截断或加快配音。');
 return quantize(Math.max(video,audio||0));
}
export function makeTimeline(segments,coverSeconds=0){
 let at=0;const list=[];
 if(coverSeconds){list.push({kind:'cover',duration:coverSeconds,start:0,end:coverSeconds});at=coverSeconds}
 for(const seg of segments){const item={...seg,start:at,end:at+seg.duration};list.push(item);at=item.end}
 return {segments:list,duration:at};
}
export function combinedCues(timeline){return timeline.segments.flatMap(seg=>(seg.cues||[]).map(c=>({...c,start:c.start+seg.start,end:c.end+seg.start})));}
export function srtText(cues){const stamp=t=>{let ms=Math.round(t*1000);const h=Math.floor(ms/3600000);ms%=3600000;const m=Math.floor(ms/60000);ms%=60000;const s=Math.floor(ms/1000);return [h,m,s].map(n=>String(n).padStart(2,'0')).join(':')+','+String(ms%1000).padStart(3,'0')};return cues.map((c,i)=>(i+1)+'\n'+stamp(c.start)+' --> '+stamp(c.end)+'\n'+c.text+'\n').join('\n');}
export function fitRect(sw,sh,x,y,w,h){const ratio=Math.min(w/sw,h/sh);return {x:x+(w-sw*ratio)/2,y:y+(h-sh*ratio)/2,w:sw*ratio,h:sh*ratio};}
export function wrapText(text,measure,maxWidth){
 const lines=[];
 for(const para of text.split('\n')){
  let line='';for(const unit of para.match(/\S+\s*|\s+/gu)||['']){
   if(measure(line+unit)<=maxWidth){line+=unit;continue}
   if(line.trim()){lines.push(line.trimEnd());line=''}
   if(measure(unit)<=maxWidth){line=unit;continue}
   for(const ch of Array.from(unit)){if(line&&measure(line+ch)>maxWidth){lines.push(line.trimEnd());line=''}line+=ch}
  }
  if(line.trim())lines.push(line.trimEnd());
 }
 return lines;
}
export function pageAt(text,t,begin,end,measure,width,maxLines){
 const lines=wrapText(text,measure,width);const pages=[];for(let i=0;i<lines.length;i+=maxLines)pages.push(lines.slice(i,i+maxLines));
 if(!pages.length)return [];
 const weights=pages.map(p=>p.join('').length||1),total=weights.reduce((a,b)=>a+b,0);let n=Math.min(.999999,Math.max(0,(t-begin)/(end-begin)))*total;
 for(let i=0;i<pages.length;i++){if(n<weights[i])return pages[i];n-=weights[i]}
 return pages.at(-1);
}
export function safeName(s){return (s||'手机成片').replace(/[<>:"/\\|?*\u0000-\u001F]/g,'_').replace(/[ .]+$/,'').slice(0,80)||'手机成片';}
