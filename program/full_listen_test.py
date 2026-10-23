import json,tempfile,threading,unittest
from pathlib import Path
import numpy as np
from media import probe
from full_listen import preview_full

class FullListenTests(unittest.TestCase):
    def test_full_preview_exceeds_spot_check_limit_and_uses_cleaned_audio(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);r=16000;t=np.arange(r*65)/r
            (.1*np.sin(2*np.pi*180*t)).astype('float32').tofile(p/'original.f32')
            np.zeros(len(t),dtype='float32').tofile(p/'enhanced.f32')
            (p/'analysis.json').write_text(json.dumps(dict(job={'audio_profile':'v11_deep'},rate=r,channels=1)),encoding='utf8')
            cancel=threading.Event();a=preview_full(p,cancel,True);b=preview_full(p,cancel,False)
            for f in [a,b]:self.assertAlmostEqual(float(probe(f,cancel)['format']['duration']),65,delta=.15)
            self.assertNotEqual(a,b);self.assertIn('整段_',Path(b).name)
            (p/'enhanced.f32').unlink()
            with self.assertRaisesRegex(ValueError,'请先完成声音处理'):preview_full(p,cancel,False)
    def test_full_project_preview_includes_latest_manual_mute(self):
        import clean_project as cp
        import clean_project_test as fixture
        fixture.CleanTests.setUpClass()
        try:
            f=fixture.CleanTests
            p=Path(cp.prepare(dict(video=str(f.video),source_srt=str(f.srt),output=str(f.root),auto_cut=False),f.cancel,make_previews=False))
            cp.edit(p,1.4,1.9,'mute',f.cancel)
            out=preview_full(p,f.cancel,False)
            self.assertAlmostEqual(float(probe(out,f.cancel)['format']['duration']),4,delta=.15)
            report=json.loads((p/'声音处理明细.json').read_text())
            self.assertTrue(any(e['kind']=='mute' for e in report['entries']))
        finally:fixture.CleanTests.tearDownClass()

if __name__=='__main__':unittest.main()
