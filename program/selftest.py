"""Synthetic regression suite; real-media runs are recorded separately."""
import unittest,tempfile,threading,json,os,wave,subprocess
from pathlib import Path
import numpy as np
from media import run,executable,parse_srt,Cancelled
from audio_edit import apply,mapped,validate_events,propose
from engine import prepare,render
class Tests(unittest.TestCase):
    def test_pauses_preserve_voiced_samples(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);r=16000;x=np.concatenate([np.sin(np.arange(r)*.04)*.1,np.zeros(2*r),np.sin(np.arange(r)*.05)*.1]).astype('float32')[:,None];x.tofile(p/'in.f32')
            ev=[dict(enabled=True,kind='cut',start=1.4,end=2.6,seconds=1.2,safe_start=1,safe_end=3,reason='test')]
            duration=apply(p/'in.f32',p/'out.f32',r,1,ev,threading.Event());y=np.fromfile(p/'out.f32',np.float32)
            self.assertAlmostEqual(duration,2.8);np.testing.assert_array_equal(x[:r,0],y[:r]);np.testing.assert_array_equal(x[3*r:,0],y[round(1.8*r):]);self.assertAlmostEqual(mapped(3,ev),1.8)

    def test_reject_bad_plan(self):
        with self.assertRaises(ValueError):validate_events([dict(enabled=True,kind='cut',start=0,end=3,seconds=3,safe_start=1,safe_end=2)],5)
    def test_invalid_srt(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.srt';p.write_text('1\n00:00:02,000 --> 00:00:01,000\nBad\n')
            with self.assertRaises(ValueError):parse_srt(p)
    def test_cancel(self):
        c=threading.Event();c.set()
        with self.assertRaises(Cancelled):run([executable('ffmpeg'),'-v','error','-f','lavfi','-i','sine=duration=60','-f','null','-'],c)
    def test_word_regions_protected(self):
        with tempfile.TemporaryDirectory() as d:
            raw=Path(d)/'voice.f32';np.zeros((64000,1),np.float32).tofile(raw)
            cues=[(1,0,4,'A reference sentence.')]
            safe=propose(cues,[(1,3)],4,16000,1,raw,True,[{'start':0,'end':.8},{'start':3.2,'end':4}]);self.assertEqual(len(safe),1)
            protected=propose(cues,[(1,3)],4,16000,1,raw,True,[{'start':1.4,'end':2.6}]);self.assertEqual(protected,[])
    def test_changed_input_rejected(self):
        from engine import fingerprint
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);asset=p/'source';asset.write_bytes(b'original');job={'video':str(asset)}
            (p/'analysis.json').write_text(json.dumps({'job':job,'fingerprint':fingerprint(job)}))
            asset.write_bytes(b'changed material')
            with self.assertRaisesRegex(ValueError,'发生变化'):render(p,threading.Event())
    def test_twenty_minute_complete_pipeline(self):
        with tempfile.TemporaryDirectory(prefix='yn-long-') as d:
            p=Path(d);c=threading.Event();ff=executable('ffmpeg')
            run([ff,'-v','error','-y','-f','lavfi','-i','testsrc2=size=96x64:rate=2:duration=1200','-c:v','libx264','-preset','ultrafast',str(p/'video.mp4')],c)
            run([ff,'-v','error','-y','-f','lavfi','-i','sine=frequency=440:sample_rate=16000:duration=1200','-c:a','pcm_s16le',str(p/'audio.wav')],c)
            text='1\n00:00:00,100 --> 00:09:59,900\nHello, world.\n\n2\n00:10:00,000 --> 00:19:59,900\nEnglish & français.\n';(p/'a.srt').write_text(text,encoding='utf8')
            job=dict(video=str(p/'video.mp4'),audio=str(p/'audio.wav'),source_srt=str(p/'a.srt'),target_srt=str(p/'a.srt'),output=str(p/'out'),language='fr',alignment='timed',trim=False,denoise=False,burn=True,erase_method='off')
            folder=Path(prepare(job,c));audio_before=json.loads((folder/'audio_versions.json').read_text(encoding='utf8'))['B'];render(folder,c);self.assertEqual(audio_before,json.loads((folder/'audio_versions.json').read_text(encoding='utf8'))['B']);report=json.loads((folder/'report.json').read_text(encoding='utf8'));self.assertTrue(report['full_decode_passed']);self.assertAlmostEqual(report['output_seconds'],1200,delta=.1);self.assertEqual(report['resolution'],[96,64]);self.assertEqual(report['fps'],'2');self.assertEqual(report['speech_speed'],1.0)
            self.assertEqual([c[3] for c in parse_srt(folder/'subtitles.srt')],[c[3] for c in parse_srt(p/'a.srt')])
            self.assertNotEqual((p/'video.mp4').resolve(),(folder/'video.mp4').resolve())
if __name__=='__main__':unittest.main(verbosity=2)
