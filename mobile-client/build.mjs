import {build} from 'esbuild';import {mkdir,copyFile,writeFile,readdir} from 'node:fs/promises';
await build({entryPoints:['src/app.mjs'],bundle:true,format:'esm',target:['safari17.4','chrome120'],outfile:'dist/app.js',minify:true,legalComments:'linked'});
await build({entryPoints:['src/qa.mjs'],bundle:true,format:'esm',target:['safari17.4','chrome120'],outfile:'dist/qa.js',minify:true,legalComments:'linked'});
await mkdir('dist/licenses',{recursive:true});
for(const [from,to] of [['node_modules/mediabunny/LICENSE','mediabunny.txt'],['node_modules/@mediabunny/aac-encoder/LICENSE','aac-encoder.txt'],['node_modules/@mediabunny/aac-encoder/licenses/ffmpeg/COPYING.LGPLv2.1','ffmpeg-lgpl.txt'],['node_modules/@mediabunny/aac-encoder/licenses/ffmpeg/LICENSE.md','ffmpeg-notes.txt']])await copyFile(from,'dist/licenses/'+to);
console.log('Built phone-local studio with bundled media and AAC engine.');

await build({entryPoints:['src/alignment-worker.mjs'],bundle:true,format:'esm',target:['safari17.4','chrome120'],outfile:'dist/alignment-worker.js',minify:true,legalComments:'linked'});
await mkdir('dist/onnx',{recursive:true});
for(const f of await readdir('node_modules/onnxruntime-web/dist'))if(/^ort-wasm-simd-threaded(?:\.jsep)?\.(?:mjs|wasm)$/.test(f))await copyFile('node_modules/onnxruntime-web/dist/'+f,'dist/onnx/'+f);
for(const [from,to] of [['node_modules/@huggingface/transformers/LICENSE','transformers-js.txt'],['third-party/onnxruntime-LICENSE.txt','onnxruntime.txt']])await copyFile(from,'dist/licenses/'+to);

if(process.env.YANGNING_SYNC_QA==='1'){await copyFile('test/sync-qa.html','dist/sync-qa.html');await build({entryPoints:['src/sync-qa.mjs'],bundle:true,format:'esm',target:['safari17.4','chrome120'],outfile:'dist/sync-qa.js',minify:true,legalComments:'linked'});}

await mkdir('dist/dict',{recursive:true});
for(const f of await readdir('node_modules/kuromoji/dict'))if(f.endsWith('.dat.gz'))await copyFile('node_modules/kuromoji/dict/'+f,'dist/dict/'+f);
await copyFile('node_modules/kuromoji/LICENSE-2.0.txt','dist/licenses/kuromoji.txt');

await copyFile('node_modules/kuromoji/NOTICE.md','dist/licenses/ipadic-notice.txt');
