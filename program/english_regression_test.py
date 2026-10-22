import json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import multilingual as m
import workflow
class EnglishRegression(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name);self.f=self.p/'input';self.f.touch()
        self.job=dict(video=str(self.f),audio=str(self.f),source_srt=str(self.f),output=str(self.p),language='en')
    def test_auto_and_saved_english_jobs_use_reference_model(self):
        for mode in ('auto','english'):
            j=workflow.normalize(dict(self.job,alignment=mode));self.assertEqual(j['alignment'],'multi');self.assertEqual(j['target_srt'],j['source_srt'])
    def test_corrected_srt_mode_stays_explicit(self):
        j=workflow.normalize(dict(self.job,alignment='timed',target_srt=str(self.f)));self.assertEqual(j['alignment'],'timed')
    def test_bilingual_reference_uses_separate_english_lines(self):
        cues=[(1,50,60,"你坐在这里\nYou sit here."),(2,61,70,'身体和心不动\nBecause your body and mind\nare unmoved.')]
        result=m.english_reference(cues);self.assertEqual(result[0],(1,50,60,'You sit here.'));self.assertEqual(result[1][3],'Because your body and mind\nare unmoved.')
    def test_no_invented_translation(self):
        with self.assertRaisesRegex(ValueError,'第7句'):m.english_reference([(7,0,1,'你坐在这里')])
    def test_wrong_old_times_do_not_enter_model_request(self):
        def run(req,folder,cancel,progress):
            request=json.loads(req.read_text(encoding='utf8'));self.assertEqual(request['language'],'en');self.assertNotIn('start',request);self.assertEqual(request['text'],'You sit here.')
            (folder/'multilingual_result.json').write_text(json.dumps({'segments':[{'words':[dict(word='You sit here.',start=.2,end=1.5)]}]}))
        with patch.object(m,'_worker_run',side_effect=run):result=m.align([(1,90,99,'You sit here.')],self.f,self.p,threading.Event(),lambda _:None,'en',2.)
        self.assertEqual(result,[(1,.2,1.5,'You sit here.')]);self.assertTrue(json.loads((self.p/'alignment_diagnostics.json').read_text(encoding='utf8'))['reference_times_ignored'])
    def test_failure_diagnostic_does_not_blame_old_times(self):
        def run(req,folder,cancel,progress):(folder/'multilingual_result.json').write_text(json.dumps({'segments':[{'words':[]}]}))
        with patch.object(m,'_worker_run',side_effect=run),self.assertRaisesRegex(ValueError,'第9句'):m.align([(9,90,99,'You sit here.')],self.f,self.p,threading.Event(),lambda _:None,'en',2.)
        diagnostic=json.loads((self.p/'alignment_diagnostics.json').read_text(encoding='utf8'));self.assertEqual(diagnostic['status'],'failed');self.assertTrue(diagnostic['reference_times_ignored'])
if __name__=='__main__':unittest.main(verbosity=2)
