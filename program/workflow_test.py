"""Headless tests for one-click inputs and terminal task states."""
import unittest,tempfile,threading
from pathlib import Path
from unittest.mock import patch
import workflow
class OneClickTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=Path(self.tmp.name);self.file=p/'input';self.file.touch()
        self.job=dict(id='one',video=str(self.file),audio=str(self.file),source_srt=str(self.file),output=str(p),alignment='english',language='en')
    def test_third_row_reused_without_fourth(self):
        j=workflow.normalize(self.job)
        self.assertEqual(j['target_srt'],j['source_srt']);self.assertNotIn('target_srt',self.job)
    def test_independent_reference_preserved(self):
        p=Path(self.tmp.name)/'reference';p.touch()
        j=workflow.normalize(dict(self.job,target_srt=str(p)));self.assertEqual(j['target_srt'],str(p))
    def test_non_english_requires_timed_srt(self):
        with self.assertRaisesRegex(ValueError,'更多设置'):workflow.normalize(dict(self.job,language='ja',alignment='timed'))
    def test_full_pipeline_one_action(self):
        events=[]
        with patch.object(workflow,'prepare',return_value=self.tmp.name) as prep,patch.object(workflow,'render',return_value=self.tmp.name) as render:
            result=workflow.execute(self.job,threading.Event(),events.append)
        self.assertEqual(result,self.tmp.name);self.assertEqual(prep.call_count,1);self.assertEqual(render.call_count,1)
        self.assertEqual(prep.call_args[0][0]['target_srt'],self.job['source_srt'])
        states=[e for e in events if e[0]=='state'];self.assertEqual(states[-1][2],'完成·检查通过')
    def test_alignment_failure_stays_failed(self):
        events=[]
        with patch.object(workflow,'prepare',side_effect=RuntimeError('英语组件缺失')),patch.object(workflow,'render') as render:
            self.assertIsNone(workflow.execute(self.job,threading.Event(),events.append))
        last=[e for e in events if e[0]=='state'][-1]
        self.assertEqual(last[2],'失败');self.assertEqual(last[3]['error'],'英语组件缺失');render.assert_not_called()
        self.assertNotIn('待处理',[e[2] for e in events if e[0]=='state'])
    def test_export_failure_stays_failed(self):
        events=[]
        with patch.object(workflow,'prepare',return_value=self.tmp.name),patch.object(workflow,'render',side_effect=RuntimeError('磁盘已满')):
            workflow.execute(self.job,threading.Event(),events.append)
        self.assertEqual([e for e in events if e[0]=='state'][-1][3]['error'],'磁盘已满')
    def test_cancel_records_stopped(self):
        events=[];cancel=threading.Event();cancel.set()
        with patch.object(workflow,'prepare') as prep:workflow.execute(self.job,cancel,events.append)
        prep.assert_not_called();self.assertEqual([e for e in events if e[0]=='state'][-1][2],'已停止')
    def test_analysis_only_does_not_export(self):
        events=[]
        with patch.object(workflow,'prepare',return_value=self.tmp.name),patch.object(workflow,'render') as render:workflow.execute(self.job,threading.Event(),events.append,export=False)
        render.assert_not_called();self.assertEqual([e for e in events if e[0]=='state'][-1][2],'待导出')
if __name__=='__main__':unittest.main(verbosity=2)
