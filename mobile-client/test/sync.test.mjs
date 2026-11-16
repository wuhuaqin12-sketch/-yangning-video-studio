import {test} from 'node:test';import assert from 'node:assert/strict';
import {boundedWords,alignReference,pictureTimeline,sourceTimeAt,normalized} from '../src/sync.mjs';
test('only a small final padded-token overrun is bounded, never arbitrary bad timestamps',()=>{
 const a=boundedWords([{text:'水',timestamp:[.28,.6]},{text:'です',timestamp:[2.68,3.6]}],3.19);assert.equal(a.words[1].end,3.19);assert.equal(a.corrections,1);
 assert.throws(()=>boundedWords([{text:'a',timestamp:[0,4.5]}],3),/超出/);
 assert.throws(()=>boundedWords([{text:'a',timestamp:[0,3.3]},{text:'b',timestamp:[2,3]}],3),/超出/);
 assert.throws(()=>boundedWords([{text:'a',timestamp:[1,2]},{text:'b',timestamp:[.2,1]}],3),/顺序/);
});
test('reference text is preserved, small recognition spelling differences do not replace it',()=>{
 const refs=[{start:0,end:2,text:'水をマレーシアから買わなくてはならないのです。'}];
 const words=[{text:'水をマレーシーから変わなくてはならないのです',timestamp:[.2,3.6]}];
 const result=alignReference(refs,words,3.19);assert.equal(result.cues[0].text,refs[0].text);assert.equal(result.cues[0].end,3.19);assert(result.coverage>.8);
});
test('missing first lines, wrong language and extra spoken material fail instead of silently aligning',()=>{
 const cues=[{start:0,end:1,text:'第一句话完整保留'},{start:2,end:3,text:'第二句话也不能截断'},{start:4,end:5,text:'最后一段结束'}];
 assert.throws(()=>alignReference(cues,[{text:'最后一段结束',timestamp:[0,2]}],3),/匹配不足|未可靠/);
 assert.throws(()=>alignReference(cues,[{text:'This is totally unrelated.',timestamp:[0,2]}],3),/匹配不足/);
 const extra='开头遗漏内容'.repeat(15)+cues.map(c=>c.text).join('');assert.throws(()=>alignReference(cues,[{text:extra,timestamp:[0,10]}],10),/匹配不足/);
});
test('picture anchors match every sentence, preserve narration speed, head and unsubtitled tail',()=>{
 const src=[{start:1,end:3,text:'first'},{start:4,end:6,text:'second'}],target=[{start:.2,end:4.2,text:'first'},{start:5,end:9,text:'second'}];
 const t=pictureTimeline(src,target,8,10);assert.equal(t.voiceOffset,.8);assert(Math.abs(t.duration-11.8)<.05);
 for(let i=0;i<2;i++){assert(Math.abs(sourceTimeAt(t.points,t.cues[i].start)-src[i].start)<1e-8);assert(Math.abs(sourceTimeAt(t.points,t.cues[i].end)-src[i].end)<1e-8)}
 assert.equal(sourceTimeAt(t.points,t.duration),8);let last=0;for(let p=0;p<t.duration;p+=.02){const x=sourceTimeAt(t.points,p);assert(x>=last);last=x}
});
test('intro and body mappings remain independent and continuous gaps cannot silently drop source frames',()=>{
 const c=[{start:0,end:1,text:'a'},{start:2,end:3,text:'b'}];assert.throws(()=>pictureTimeline(c,[{start:0,end:2,text:'a'},{start:2,end:3,text:'b'}],4,4),/停顿/);
 const result=pictureTimeline([{start:0,end:1,text:'body'}],[{start:.3,end:1.4,text:'body'}],2,2);assert.equal(result.cues[0].start,.3);assert.equal(result.voiceOffset,0);
 assert.throws(()=>pictureTimeline([{start:0,end:5,text:'a'}],[{start:0,end:1,text:'a'}],2,2),/超出/);
});
