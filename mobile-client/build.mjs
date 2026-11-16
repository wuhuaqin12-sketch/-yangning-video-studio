import {build} from 'esbuild';import {mkdir,copyFile,writeFile} from 'node:fs/promises';
await build({entryPoints:['src/app.mjs'],bundle:true,format:'esm',target:['safari17.4','chrome120'],outfile:'dist/app.js',minify:true,legalComments:'linked'});
await build({entryPoints:['src/qa.mjs'],bundle:true,format:'esm',target:['safari17.4','chrome120'],outfile:'dist/qa.js',minify:true,legalComments:'linked'});
await mkdir('dist/licenses',{recursive:true});
for(const [from,to] of [['node_modules/mediabunny/LICENSE','mediabunny.txt'],['node_modules/@mediabunny/aac-encoder/LICENSE','aac-encoder.txt'],['node_modules/@mediabunny/aac-encoder/licenses/ffmpeg/COPYING.LGPLv2.1','ffmpeg-lgpl.txt'],['node_modules/@mediabunny/aac-encoder/licenses/ffmpeg/LICENSE.md','ffmpeg-notes.txt']])await copyFile(from,'dist/licenses/'+to);
console.log('Built phone-local studio with bundled media and AAC engine.');
