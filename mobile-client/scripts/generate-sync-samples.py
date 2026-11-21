import wave,json,math,struct,subprocess,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=root/'.sites-runtime'/'sync-fixtures';p.mkdir(parents=True,exist_ok=True)
out=root/'dist'/'sync-test-data';out.mkdir(exist_ok=True)
url='https://datasets-server.huggingface.co/rows?dataset=japanese-asr/ja_asr.jsut_basic5000&config=default&split=test&offset=0&length=4'
data=json.load(urllib.request.urlopen(url));rows=[]
for item in data['rows']:
 i=item['row_idx'];row=item['row'];audio=row['audio'][0]['src']
 if '278db379fc96167ff2293d7abf9ab86976afcd78' not in audio:raise RuntimeError('Evaluation dataset changed; review before using new fixtures.')
 raw=p/f'ja_{i}.wav';wav=p/f'ja_{i}_16.wav'
 if not raw.exists():urllib.request.urlretrieve(audio,raw)
 subprocess.run(['ffmpeg','-v','error','-y','-i',str(raw),'-ar','16000','-ac','1',str(wav)],check=True)
 with wave.open(str(wav)) as w:duration=w.getnframes()/w.getframerate()
 rows.append((i,row['transcription'],duration))
voice=[];bounds=[];sr=16000
voice.extend([0]*int(.4*sr))
for i,text,duration in rows:
 with wave.open(str(p/f'ja_{i}_16.wav')) as w:audio=struct.unpack('<'+'h'*w.getnframes(),w.readframes(w.getnframes()))
 begin=len(voice)/sr;voice.extend(audio);bounds.append((begin,len(voice)/sr,text));voice.extend([0]*round((.6 if i!=2 else .9)*sr))
with wave.open(str(out/'voice.wav'),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(sr);w.writeframes(struct.pack('<'+'h'*len(voice),*voice))
source=[(.5,2.5),(3,6.5),(7,9.5),(10,12.5)]
def stamp(t):return f'00:00:{int(t):02d},{round((t%1)*1000):03d}'
(out/'source.srt').write_text('\n\n'.join(f'{i+1}\n{stamp(a)} --> {stamp(b)}\n{rows[i][1]}' for i,(a,b) in enumerate(source)),encoding='utf8')
colors=['#a94b35','#258158','#365ba9','#9252a4'];filters=[]
for (a,b),color in zip(source,colors):filters.append(f"drawbox=x=0:y=0:w=iw:h=ih:color={color}:t=fill:enable='between(t,{a},{b-.001})'")
subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=gray:s=640x360:r=24:d=14','-f','lavfi','-i','sine=frequency=440:duration=14','-vf',','.join(filters),'-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(out/'source.mp4')],check=True)
(out/'expected.json').write_text(json.dumps({'voiceDuration':len(voice)/sr,'voiceSegments':bounds,'sourceCues':source,'sourceDuration':14,'colors':colors,'sourceDataset':'japanese-asr/ja_asr.jsut_basic5000','datasetRevision':'278db379fc96167ff2293d7abf9ab86976afcd78','use':'Internal QA only; excluded from published assets'},ensure_ascii=False,indent=2))
print('voice seconds',len(voice)/sr,bounds)
