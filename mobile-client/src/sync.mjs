// All times below are local to one segment; audio is never time-stretched.
export const MODEL={id:'onnx-community/whisper-base_timestamped',revision:'608c49e61301901684bc36cac8f74b95ff6b5a8e',dtype:'q8'};
export const LANGUAGE={日语:'japanese',英语:'english',法语:'french',德语:'german',印尼语:'indonesian',中文:'chinese'};
export function normalized(text){return Array.from(text.normalize('NFKC').toLocaleLowerCase().replace(/[^\p{L}\p{N}]/gu,''));}
export function boundedWords(chunks,duration){
 if(!(duration>0)||!chunks?.length)throw Error('配音定位没有返回有效词语。');
 chunks=chunks.filter(c=>normalized(c.text).length);if(!chunks.length)throw Error('配音定位没有返回有效文字。');
 const out=[];let corrections=0;
 for(let i=0;i<chunks.length;i++){
  const c=chunks[i],start=c.timestamp?.[0],rawEnd=c.timestamp?.[1];
  if(!Number.isFinite(start)||!Number.isFinite(rawEnd)||start<0||rawEnd<start||start>=duration)throw Error('配音定位时间异常，请缩短片段或重新校对配音。');
  // Whisper can extrapolate the last token into its padded input. Only bound
  // a small FINAL overrun; never rescale an entire transcript to hide bad timing.
  if(rawEnd>duration){if(i!==chunks.length-1||rawEnd-duration>.8)throw Error('配音定位超出真实音频范围，已停止同步。');corrections++}
  if(out.length&&start<out.at(-1).start-.021)throw Error('配音定位顺序异常，已停止同步。');
  out.push({text:c.text,start,end:Math.min(rawEnd,duration)});
 }
 return {words:out,corrections};
}
function referenceMatch(ref,hyp){
 const n=ref.length,m=hyp.length;
 if(!n||!m||n*m>20000000)throw Error('参考稿或识别文字过长／为空，请分成较短片段进行本机同步。');
 const dir=new Uint8Array((n+1)*(m+1));let prev=new Uint16Array(m+1),cur=new Uint16Array(m+1);
 for(let j=0;j<=m;j++){prev[j]=j;dir[j]=2}
 for(let i=1;i<=n;i++){
  cur[0]=i;dir[i*(m+1)]=1;
  for(let j=1;j<=m;j++){
   const sub=prev[j-1]+(ref[i-1]===hyp[j-1]?0:1),del=prev[j]+1,ins=cur[j-1]+1;
   const best=Math.min(sub,del,ins);cur[j]=best;dir[i*(m+1)+j]=best===sub?0:best===del?1:2;
  }
  [prev,cur]=[cur,prev];
 }
 let i=n,j=m;const pairs=[];
 while(i||j){const d=dir[i*(m+1)+j];if(i&&j&&d===0){pairs.push({i:i-1,j:j-1,equal:ref[i-1]===hyp[j-1]});i--;j--}else if(i&&(d===1||!j))i--;else j--}
 return pairs.reverse();
}
export function alignReference(cues,chunks,voiceDuration,{minCoverage=.75,minPrecision=.70,minCue=.65}={}){
 const bounded=boundedWords(chunks,voiceDuration),hyp=[],ref=[],ranges=[];
 for(const word of bounded.words){const chars=normalized(word.text);for(let i=0;i<chars.length;i++)hyp.push({char:chars[i],start:word.start+(word.end-word.start)*i/chars.length,end:word.start+(word.end-word.start)*(i+1)/chars.length})}
 for(const cue of cues){const chars=normalized(cue.text),start=ref.length;if(!chars.length)throw Error('SRT有仅含标点的段落，请先校对。');ref.push(...chars);ranges.push({start,end:ref.length})}
 const pairs=referenceMatch(ref,hyp.map(c=>c.char)),correct=pairs.filter(p=>p.equal).length,coverage=correct/ref.length,precision=correct/hyp.length;
 if(coverage<minCoverage||precision<minPrecision)throw Error('配音与SRT文字匹配不足（参考稿 '+Math.round(coverage*100)+'%，配音 '+Math.round(precision*100)+'%）。请检查语言、漏句或配音与SRT是否同稿；未强行生成。');
 const aligned=[],scores=[];
 for(let k=0;k<cues.length;k++){
  const r=ranges[k],group=pairs.filter(p=>p.i>=r.start&&p.i<r.end),exact=group.filter(p=>p.equal),score=exact.length/(r.end-r.start);
  if(score<minCue||!group.length||!exact.length||exact[0].i-r.start>Math.max(2,Math.floor((r.end-r.start)*.2))||r.end-1-exact.at(-1).i>Math.max(2,Math.floor((r.end-r.start)*.2)))throw Error('SRT第'+(k+1)+'句未可靠定位（匹配 '+Math.round(score*100)+'%），请核对这句是否漏读或用词不同。');
  const start=hyp[group[0].j].start,end=Math.min(voiceDuration,hyp[group.at(-1).j].end);
  if(end-start<.06||start<(aligned.at(-1)?.end||0)-.021)throw Error('SRT第'+(k+1)+'句定位时间无效，已停止同步。');
  aligned.push({...cues[k],start:Math.max(start,aligned.at(-1)?.end||0),end});scores.push(score);
 }
 return {cues:aligned,coverage,precision,scores,corrections:bounded.corrections};
}
export function pictureTimeline(sourceCues,voiceCues,sourceDuration,voiceDuration,fps=24){
 if(!sourceCues.length||sourceCues.length!==voiceCues.length)throw Error('音画同步需要完整的逐句定位结果。');
 if(sourceCues.some(c=>c.start<0||c.end>sourceDuration+.08))throw Error('原画面SRT超出视频时长，请使用这段原视频对应的时间轴。');
 const head=Math.max(0,sourceCues[0].start-voiceCues[0].start);
 const tail=Math.max(0,(sourceDuration-sourceCues.at(-1).end)-(voiceDuration-voiceCues.at(-1).end));
 const duration=Math.ceil((head+voiceDuration+tail)*fps-1e-6)/fps;
 const points=[{t:0,s:0}],cues=voiceCues.map(c=>({...c,start:c.start+head,end:c.end+head}));
 for(let i=0;i<cues.length;i++){
  for(const [t,s] of [[cues[i].start,sourceCues[i].start],[cues[i].end,sourceCues[i].end]]){
   const prev=points.at(-1);
   if(t<prev.t-.001||s<prev.s-.001)throw Error('音画同步时间轴发生重叠，请校对SRT。');
   if(t-prev.t<1e-5){if(s-prev.s>.08)throw Error('配音句间没有足够停顿，无法完整映射原画面，请调整分句或配音停顿。');prev.s=Math.max(prev.s,s)}
   else points.push({t,s});
  }
 }
 const last=points.at(-1);if(duration-last.t<1e-5)last.s=sourceDuration;else points.push({t:duration,s:sourceDuration});
 return {points,cues,duration,voiceOffset:head,tail};
}
export function sourceTimeAt(points,t){
 if(!points?.length)return t;
 if(t<=points[0].t)return points[0].s;
 let lo=0,hi=points.length-1;while(hi-lo>1){const mid=(hi+lo)>>1;if(points[mid].t<=t)lo=mid;else hi=mid}
 const a=points[lo],b=points[hi];return t>=b.t?b.s:a.s+(b.s-a.s)*(t-a.t)/(b.t-a.t);
}
