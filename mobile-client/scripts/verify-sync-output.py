from pathlib import Path
import json,subprocess,os,numpy as np
p=Path(os.environ.get('YANGNING_QA_OUTPUT','.sites-runtime/sync-outputs'))
fixtures=Path(__file__).resolve().parents[1]/'dist'/'sync-test-data'
r=json.loads((p/'sync-report.json').read_text())[0]
def probe(path):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))
def pcm(path):return np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-vn','-ar','16000','-ac','1','-f','f32le','-']),dtype='<f4')
def frame(path,t,w,h):return np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-ss',str(t),'-i',str(path),'-frames:v','1','-vf',f'crop=16:16:{w//2-8}:{h//2-8}','-f','rawvideo','-pix_fmt','rgb24','-']),dtype=np.uint8).reshape(-1,3).mean(axis=0)
voice=pcm(fixtures/'voice.wav');res={}
expected=json.loads((fixtures/'expected.json').read_text())
for name,wh in [('landscape.mp4',(960,540)),('portrait.mp4',(540,960))]:
 path=p/name;info=probe(path);streams=info['streams'];vid=next(s for s in streams if s['codec_type']=='video');aud=next(s for s in streams if s['codec_type']=='audio');duration=float(info['format']['duration'])
 assert (vid['width'],vid['height'])==wh
 assert vid['codec_name']=='h264' and aud['codec_name']=='aac'
 assert abs(duration-(7+r['duration']))<.1
 subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'],check=True,capture_output=True)
 out=pcm(path);offset=round((5+r['voiceOffset'])*16000)
 spoken=out[offset:offset+len(voice)];assert len(spoken)==len(voice)
 correlations=[]
 for a,b,text in expected['voiceSegments']:
  start=round(a*16000);end=round(b*16000);x=voice[start:end];y=spoken[start:end];corr=float(np.corrcoef(x,y)[0,1]);assert corr>.97,(name,text,corr);correlations.append(corr)
 assert float(np.sqrt(np.mean(out[:3*16000]**2)))<.00001
 colors=[]
 for cue,color in zip(r['voiceCues'],expected['colors']):
  t=5+r['voiceOffset']+(cue['start']+cue['end'])/2
  found=frame(path,t,*wh);target=np.array([int(color[i:i+2],16) for i in (1,3,5)]);assert np.max(np.abs(found-target))<20,(found,target)
  colors.append(found.tolist())
 # Outro is a separate 2-second source and must survive after the retimed body.
 tail=out[round((5+r['duration']+.25)*16000):round((5+r['duration']+1.75)*16000)]
 freq=np.fft.rfftfreq(len(tail),1/16000)[np.argmax(np.abs(np.fft.rfft(tail)))];assert abs(freq-880)<2
 res[name]={'duration':duration,'size':[vid['width'],vid['height']],'full_decode':True,'voice_sentence_correlations':correlations,'body_frames_follow_each_cue':True,'outro_tone_hz':float(freq),'cover_silent':True}
pv=probe(p/'preview20.mp4');assert abs(float(pv['format']['duration'])-20)<.05
res['preview20']={'duration':float(pv['format']['duration'])}
res['physical_phone_verified']=False;res['actual_user_diamond_sutra_verified']=False
(p/'verification.json').write_text(json.dumps(res,ensure_ascii=False,indent=2))
print(json.dumps(res,ensure_ascii=False,indent=2))
