import kuromoji from 'kuromoji/build/kuromoji.js';
let loading;
async function tokenizer(){return loading ||= new Promise((resolve,reject)=>kuromoji.builder({dicPath:'/dict/'}).build((e,t)=>e?reject(e):resolve(t)))}
export function kana(text){return text.normalize('NFKC').replace(/[ァ-ヶ]/g,c=>String.fromCharCode(c.charCodeAt(0)-0x60)).replace(/[^\p{L}\p{N}ー]/gu,'');}
export async function japaneseReadings(result,references){
 const tok=await tokenizer();
 const reading=text=>tok.tokenize(text).map(t=>kana(t.reading||t.surface_form)).join('');
 const joined=result.chunks.map(c=>c.text).join('');let pos=0;const spans=result.chunks.map(c=>{const out={a:pos,b:pos+c.text.length,start:c.timestamp[0],end:c.timestamp[1]};pos=out.b;return out});
 const chunks=[];
 for(const token of tok.tokenize(joined)){
  const a=token.word_position-1,b=a+token.surface_form.length,overlaps=spans.filter(s=>s.b>a&&s.a<b),text=kana(token.reading||token.surface_form);
  if(!text||!overlaps.length)continue;
  const first=overlaps[0],last=overlaps.at(-1);
  const timeAt=(s,p)=>s.start+(s.end-s.start)*Math.max(0,Math.min(1,(p-s.a)/(s.b-s.a)));
  chunks.push({text,timestamp:[timeAt(first,a),timeAt(last,b)]});
 }
 return {references:references.map(reading),chunks};
}
