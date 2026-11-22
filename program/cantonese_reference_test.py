import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from cantonese_reference import remap
from project_vnext import save_project,load_project,processing_key
from workflow import normalize

class CantoneseReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.chinese=[(1,0,2,'第一句'),(2,2,4,'第二句'),(3,4,6,'第三句')]
        self.aligned=[(1,0,3,'第一句'),(2,3,7,'第二句'),(3,7,9,'第三句')]
    def test_split_and_merge_preserve_yue_text_and_record_references(self):
        yue=[(11,0,1,'第一句上'),(12,1,2,'第一句下'),(13,2,6,'第二句同第三句')]
        result=remap(self.chinese,self.aligned,yue,self.root)
        self.assertEqual([c[3] for c in result],[c[3] for c in yue])
        self.assertEqual([(c[1],c[2]) for c in result],[(0,1.5),(1.5,3),(3,9)])
        mapping=json.loads((self.root/'cantonese_cue_mapping.json').read_text())
        self.assertEqual(mapping[-1]['chinese_ids'],[2,3])
    def test_displacement_and_overlap_fail_with_cue_number(self):
        with self.assertRaisesRegex(ValueError,'第11条'):
            remap(self.chinese,self.aligned,[(11,7,8,'错位')],self.root)
        with self.assertRaisesRegex(ValueError,'粤语 SRT 顺序'):
            remap(self.chinese,self.aligned,[(11,0,2,'甲'),(12,1,3,'乙')],self.root)
    def test_mode_requires_chinese_only_when_selected_and_old_projects_load(self):
        for key in ('video','audio','source_srt'):(self.root/key).write_text('test')
        job={key:str(self.root/key) for key in ('video','audio','source_srt')}
        job.update(language='yue',alignment='auto',output=str(self.root))
        with self.assertRaisesRegex(ValueError,'中文参考 SRT'):normalize({**job,'cantonese_alignment':'chinese'})
        direct=normalize({**job,'cantonese_alignment':'direct'})
        self.assertEqual(direct['alignment'],'multi')
        chinese=self.root/'chinese.srt';chinese.write_text('中文')
        assisted=normalize({**job,'chinese_srt':str(chinese),'cantonese_alignment':'chinese'})
        self.assertNotEqual(processing_key(assisted),processing_key(direct))
        saved=self.root/'old.json';save_project(saved,{**job,'sequence':{}})
        restored,missing=load_project(saved)
        self.assertFalse(missing);self.assertNotIn('chinese_srt',restored)
        self.assertEqual(normalize(restored)['cantonese_alignment'],'direct')
