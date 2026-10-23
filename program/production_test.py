import hashlib,json,unittest
from pathlib import Path
import clean_project as cp
import clean_project_test as fixture
from production import same_material,finish

class ProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixture.CleanTests.setUpClass();cls.f=fixture.CleanTests
    @classmethod
    def tearDownClass(cls):fixture.CleanTests.tearDownClass()
    def project(self):
        f=self.f
        values=dict(video=str(f.video),audio='',source_srt=str(f.srt),audio_reference_srt='',output=str(f.root),auto_cut=False,audio_profile='off',audio_separate=False)
        folder=Path(cp.prepare(values,f.cancel,make_previews=False));cp.edit(folder,1.4,1.9,'mute',f.cancel)
        return folder,values
    def test_final_export_preserves_confirmed_mutes_and_enhanced_pcm(self):
        folder,v=self.project();before=hashlib.sha256((folder/'enhanced.wav').read_bytes()).hexdigest()
        self.assertTrue(same_material(folder,v))
        output=finish(folder,v,{},True,self.f.cancel)
        self.assertTrue(Path(output).is_file());self.assertEqual(len(cp.load(folder)['edits']),1)
        self.assertEqual(before,hashlib.sha256((folder/'enhanced.wav').read_bytes()).hexdigest())
        report=json.loads((folder/'声音处理明细.json').read_text());self.assertTrue(any(e['kind']=='mute' for e in report['entries']))
    def test_changed_sound_options_do_not_discard_old_edits(self):
        folder,v=self.project();v['audio_profile']='v11_deep'
        with self.assertRaisesRegex(ValueError,'声音设置已改变'):finish(folder,v,{},False,self.f.cancel)
        self.assertEqual(len(cp.load(folder)['edits']),1);self.assertFalse((folder/'video.mp4').exists())
    def test_new_output_directory_receives_video_subtitles_and_audit(self):
        folder,v=self.project();v['output']=str(self.f.root/'new_output')
        output=Path(finish(folder,v,{},False,self.f.cancel))
        self.assertEqual(output.parent.parent,Path(v['output']))
        self.assertTrue((output.parent/'声音处理明细.txt').is_file());self.assertTrue((output.parent/'subtitles.srt').is_file())
        self.assertFalse((output.parent/'enhanced.wav').exists())
        other=dict(v,video='another.mp4');self.assertFalse(same_material(folder,other))

if __name__=='__main__':unittest.main()
