import {test} from 'node:test';import assert from 'node:assert/strict';
import {parseSrt,segmentLength,makeTimeline,combinedCues,srtText,fitRect,pageAt,wrapText,safeName} from '../src/core.mjs';
test('SRT keeps full text, BOM and punctuation, and rejects broken or overlapping cues',()=>{
 const cues=parseSrt('\uFEFF1\r\n00:00:00,100 --> 00:00:02,100\r\n金剛経\r\n第二行\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\nHello world!');assert.equal(cues.length,2);assert.equal(cues[0].text,'金剛経\n第二行');assert.equal(cues[1].end,4);
 assert.throws(()=>parseSrt('1\n00:00:00,000 --> 00:00:02,000\na\n\n2\n00:00:01,500 --> 00:00:03,000\nb'),/重叠/);assert.throws(()=>parseSrt('1\nno time\nhello'),/时间轴/);
});
test('Longer voice is never truncated or accelerated silently',()=>{assert.throws(()=>segmentLength(2,3,false),/不.*截断|不会截断/);assert.equal(segmentLength(2,3,true),3);assert.equal(segmentLength(4,2,false),4)});
test('Cover intro body outro keep all sections and offset only local cue time',()=>{
 const intro={kind:'intro',duration:2,cues:[{start:.2,end:1.8,text:'片头'}]},body={kind:'body',duration:5,cues:[{start:.1,end:4.5,text:'正文'}]},outro={kind:'outro',duration:4,cues:[]};const timeline=makeTimeline([intro,body,outro],3);
 assert.equal(timeline.duration,14);assert.deepEqual(timeline.segments.map(s=>s.start),[0,3,5,10]);assert.deepEqual(combinedCues(timeline).map(c=>c.start),[3.2,5.1]);assert.equal(body.cues[0].start,.1);assert.equal(parseSrt(srtText(combinedCues(timeline)))[1].end,9.5);
});
test('Fit never stretches or crops and safe names preserve Chinese orientation labels',()=>{const r=fitRect(1920,1080,0,0,540,600);assert.equal(r.w,540);assert.equal(r.w/r.h,1920/1080);assert.equal(safeName('金刚经_横版/16:9'),'金刚经_横版_16_9')});
test('Pagination preserves all text within cue time and wraps overlong words',()=>{const text='あいうえおかきくけこ';const measure=s=>Array.from(s).length;assert.deepEqual(wrapText(text,measure,3),['あいう','えおか','きくけ','こ']);const first=pageAt(text,0,0,10,measure,3,2),last=pageAt(text,9.999,0,10,measure,3,2);assert.equal(first.join('')+last.join(''),text);assert(first.length<=2&&last.length<=2)});
