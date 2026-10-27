"""Acoustic regression: Japanese broad token spans, EOF and actual MP4 duration."""
import json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from audio_edit import detect,propose,apply,mapped
from media import run,executable,parse_srt,probe
from engine import prepare,render

class PauseTests(unittest.TestCase):
    def test_broad_japanese_span_and_cueless_silence(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.f32';r=16000
            x=np.zeros((r*6,2),np.float32);x[:r]=.1;x[4*r:]=.1;x.tofile(p)
            cues=[(1,0,6,'本来の姿を観る。')]
            for words in (None,[dict(start=0,end=6,word='本来の姿を観る。')]):
                ev=propose(cues,[(1,4)],6,r,2,p,words=words)
                self.assertEqual(len(ev),1)
                total=apply(p,Path(d)/'out.f32',r,2,ev,threading.Event())
                self.assertAlmostEqual(total,3.55)
                y=np.fromfile(Path(d)/'out.f32',np.float32).reshape(-1,2)
                np.testing.assert_array_equal(y[:r],x[:r])
                np.testing.assert_array_equal(y[-2*r:],x[-2*r:])
                self.assertAlmostEqual(mapped(4,ev),1.55)
            # Quiet speech above the stricter override threshold is not cut.
            x[r:4*r]=.004;x.tofile(p)
            self.assertEqual(propose(cues,[(1,4)],6,r,2,p,words=[dict(start=0,end=6)]),[])
            # A localized real word remains protected even in low-energy audio.
            self.assertEqual(propose(cues,[(1,4)],6,r,2,p,words=[dict(start=2,end=2.4)]),[])

    def test_japanese_short_gap_and_punctuation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.f32';r=16000;x=np.zeros((4*r,1),np.float32);x[:r]=.1;x[round(1.6*r):]=.1;x.tofile(p)
            cue=[(1,0,4,'本来の姿。')]
            for left,keep,count in [('本来',.18,1),('本来、',.28,1),('本来。',None,0)]:
                words=[dict(word=left,start=0,end=1),dict(word='姿',start=1.6,end=4)]
                ev=propose(cue,[(1,1.6)],4,r,1,p,True,words,'ja')
                self.assertEqual(len(ev),count)
                if count:self.assertAlmostEqual(ev[0]['seconds'],.6-keep)
            words=[dict(word='本来',start=0,end=1),dict(word='っ',start=1.6,end=4)]
            self.assertEqual(propose(cue,[(1,1.6)],4,r,1,p,True,words,'ja'),[])
            # Do not cut a quieter voiced sample solely on a silence timestamp.
            x[r:round(1.6*r)]=.004;x.tofile(p)
            words=[dict(word='本来',start=0,end=1),dict(word='姿',start=1.6,end=4)]
            self.assertEqual(propose(cue,[(1,1.6)],4,r,1,p,True,words,'ja'),[])

    def test_default_speed_pitch_and_cache(self):
        from engine import preview_audio,save_json,playback_speed
        for language in ('en','fr','zh','de','ko','other'):
            self.assertEqual(playback_speed(dict(language=language)),1.1)
        self.assertEqual(playback_speed(dict(language='ja')),1.1)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);r=16000;c=threading.Event();ff=executable('ffmpeg')
            x=(.12*np.sin(2*np.pi*440*np.arange(4*r)/r)).astype('float32');x.tofile(p/'original.f32')
            run([ff,'-v','error','-y','-f','f32le','-ar',str(r),'-ac','1','-i',str(p/'original.f32'),str(p/'voice.wav')],c)
            from audio_edit import export_plan
            export_plan([],p/'pause_plan.csv')
            m=dict(version=__import__('engine').VERSION,rate=r,channels=1,audio_duration=4,target=[(1,0,4,'日本語。')],silences=[],job=dict(language='ja',audio=str(p/'voice.wav'),mute=False))
            save_json(p/'analysis.json',m);total,_=preview_audio(p,c);self.assertAlmostEqual(total,4/1.1)
            first=json.loads((p/'audio_versions.json').read_text(encoding='utf8'))['B']
            preview_audio(p,c);self.assertEqual(first,json.loads((p/'audio_versions.json').read_text(encoding='utf8'))['B'])
            run([ff,'-v','error','-y','-i',str(p/first),'-f','f32le','-ar',str(r),'-ac','1',str(p/'check.f32')],c)
            y=np.fromfile(p/'check.f32',np.float32)[r:2*r];spectrum=np.abs(np.fft.rfft(y*np.hanning(len(y))))
            peak=np.fft.rfftfreq(len(y),1/r)[np.argmax(spectrum)]
            self.assertAlmostEqual(peak,440,delta=2)
            m['job']['language']='fr';m['job']['speed']='1.0';save_json(p/'analysis.json',m)
            total,_=preview_audio(p,c);self.assertAlmostEqual(total,4)
            self.assertNotEqual(first,json.loads((p/'audio_versions.json').read_text(encoding='utf8'))['B'])

    def test_trailing_silence_without_end_marker(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.f32';np.zeros((16000*5,1),np.float32).tofile(p)
            with patch('audio_edit.run',return_value='silence_start: 1\nsilence_end: 2\nsilence_start: 4\n'):
                self.assertEqual(detect(p,16000,1,threading.Event()),[(1,2),(4,5)])

    def test_262_second_japanese_export(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);r=16000;c=threading.Event();ff=executable('ffmpeg')
            # 4m22s synthetic narration: 20 voiced blocks, long within-cue pauses.
            x=np.zeros(262*r,np.float32)
            for start in range(2,262,13):
                stop=min(start+10,262)
                x[start*r:stop*r]=.12*np.sin(2*np.pi*220*np.arange((stop-start)*r)/r)
            x.tofile(p/'in.f32')
            run([ff,'-v','error','-y','-f','f32le','-ar',str(r),'-ac','1','-i',str(p/'in.f32'),str(p/'voice.wav')],c)
            run([ff,'-v','error','-y','-f','lavfi','-i','testsrc2=size=96x64:rate=2:duration=262','-c:v','libx264','-preset','ultrafast',str(p/'video.mp4')],c)
            (p/'ref.srt').write_text('1\n00:00:00,000 --> 00:04:22,000\n本来の姿を観る。\n',encoding='utf8')
            job=dict(video=str(p/'video.mp4'),audio=str(p/'voice.wav'),source_srt=str(p/'ref.srt'),target_srt=str(p/'ref.srt'),output=str(p/'out'),language='ja',alignment='multi',trim=True,burn=False)
            def fake_worker(request,folder,cancel,progress):
                (folder/'multilingual_result.json').write_text(json.dumps({'segments':[{'words':[dict(word='本来の姿を観る。',start=0,end=262)]}]}),encoding='utf8')
            logs=[]
            with patch('multilingual._worker_run',side_effect=fake_worker):
                folder=Path(prepare(job,c,logs.append))
            render(folder,c,logs.append)
            report=json.loads((folder/'report.json').read_text(encoding='utf8'))
            self.assertGreater(report['removed_seconds'],45)
            self.assertAlmostEqual(report['output_seconds'],(262-report['removed_seconds'])/1.1,delta=.1)
            self.assertEqual(report['speech_speed'],1.1)
            self.assertEqual(report['resolution'],[96,64]);self.assertTrue(report['full_decode_passed'])
            self.assertLessEqual(parse_srt(folder/'subtitles.srt')[-1][2],report['output_seconds']+.05)
            self.assertTrue(any('共删除' in line for line in logs))
            print('SYNTHETIC_262_SECOND_RESULT',json.dumps(report,ensure_ascii=False))

if __name__=='__main__':unittest.main(verbosity=2)
