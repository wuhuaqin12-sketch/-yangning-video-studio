"""Real FFmpeg checks of source-backed previews, edits, sync and final export."""
import unittest,tempfile,threading,json,hashlib
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from PIL import Image
from media import run,executable,probe,parse_srt
import clean_project as cp
from publish import make_ass
from publish_style import normalize_style

class CleanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);cls.cancel=threading.Event()
        cls.video=cls.root/'source.mp4'
        run([executable('ffmpeg'),'-v','error','-y','-f','lavfi','-i','testsrc2=s=320x180:r=25:d=4','-f','lavfi','-i','sine=f=320:r=24000:d=4','-c:v','libx264','-threads','2','-c:a','aac','-shortest',str(cls.video)],cls.cancel)
        cls.srt=cls.root/'source.srt';cls.srt.write_text('1\n00:00:00,100 --> 00:00:01,300\n無我なら、そんな区別がありますか。\n\n2\n00:00:02,100 --> 00:00:03,700\n「私」があるから、動いているとか、静まっているとか思う。そうでしょう。\n',encoding='utf8')
        cls.bg=cls.root/'background.png';Image.new('RGB',(1080,1920),'#eee3ce').save(cls.bg)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def project(self):
        return Path(cp.prepare(dict(video=str(self.video),source_srt=str(self.srt),output=str(self.root),separate=False,auto_cut=False),self.cancel))
    def test_preview_does_not_export_and_streamcopy_final(self):
        f=self.project();self.assertFalse((f/'video.mp4').exists());self.assertTrue((f/'preview.mp4').exists())
        self.assertTrue((f/'试听_处理后.m4a').exists())
        original=self.video.read_bytes();out=cp.export(f,self.cancel)
        self.assertEqual(original,self.video.read_bytes())
        def h(p):return run([executable('ffmpeg'),'-v','error','-i',str(p),'-map','0:v','-c','copy','-f','hash','-hash','sha256','-'],self.cancel)
        self.assertEqual(h(out),h(self.video));self.assertTrue(json.loads((f/'export_report.json').read_text())['video_stream_copied'])
    def test_mute_cut_undo_and_srt_mapping(self):
        f=self.project();r,source=wavfile.read(f/'enhanced.wav')
        cp.edit(f,1.4,1.9,'mute',self.cancel);_,y=wavfile.read(f/'edited.wav')
        self.assertEqual(len(y),len(source));self.assertTrue(np.all(y[round(1.4*r):round(1.9*r)]==0))
        cp.undo(f,self.cancel);_,y=wavfile.read(f/'edited.wav');np.testing.assert_array_equal(y,source)
        cp.edit(f,1.4,1.9,'cut',self.cancel)
        m=cp.load(f);self.assertAlmostEqual(m['output_duration'],3.5,places=2)
        self.assertAlmostEqual(parse_srt(f/'subtitles.srt')[1][1],1.6)
        cp.preview(f,self.cancel,1.0,2.5)
        out=cp.export(f,self.cancel);info=probe(out,self.cancel);self.assertAlmostEqual(float(info['format']['duration']),3.5,delta=.12)
        cp.undo(f,self.cancel);self.assertAlmostEqual(cp.load(f)['output_duration'],4,delta=.05)
    def test_styled_preview_final_one_encode_and_uniform_fonts(self):
        f=self.project();m=cp.load(f)
        m['style']=dict(background=str(self.bg),title='本来の姿',title_y=25,cover_mode='frame',cover_time=.5)
        cp.save(f/'clean_project.json',m)
        image=cp.export(f,self.cancel,preview_time=2.5);self.assertTrue(Path(image).exists());self.assertFalse((f/'video.mp4').exists())
        ass=(f/'publish.ass').read_text('utf-8-sig');self.assertEqual(ass.count(r'\fs47'),2)
        report=json.loads((f/'layout_report.json').read_text());self.assertEqual(report['subtitle_actual_px'],[47]);self.assertFalse(report['shrunk_cues'])
        out=cp.export(f,self.cancel);info=probe(out,self.cancel);v=next(s for s in info['streams'] if s['codec_type']=='video')
        self.assertEqual((v['width'],v['height']),(1080,1920));self.assertTrue((f/'cover.png').exists())
        self.assertEqual(json.loads((f/'export_report.json').read_text())['video_encodes'],1)
    def test_invalid_edits_and_changed_source(self):
        f=self.project()
        for a,b in [(-1,2),(2,1),(0,float('nan')),(0,9)]:
            with self.assertRaises(ValueError):cp.edit(f,a,b,'cut',self.cancel)
        cp.edit(f,.5,.8,'mute',self.cancel)
        with self.assertRaises(ValueError):cp.edit(f,.7,.9,'cut',self.cancel)
        other=f/'replacement.srt';other.write_text('changed');m=cp.load(f);m['sources']['srt']=cp.identity(other);cp.save(f/'clean_project.json',m);other.write_text('different')
        with self.assertRaisesRegex(ValueError,'源素材已变化'):cp.preview(f,self.cancel)
    def test_undo_is_action_order_and_cuts_sorted(self):
        f=self.project();cp.edit(f,2.7,2.9,'cut',self.cancel);cp.edit(f,.4,.6,'cut',self.cancel)
        self.assertEqual([e['start'] for e in cp.load(f)['cuts']],[.4,2.7])
        cp.undo(f,self.cancel);self.assertEqual([e['start'] for e in cp.load(f)['edits']],[2.7])
    def test_alignment_analysis_style_preview_then_single_export(self):
        from engine import prepare,render,render_preview,save_json
        audio=self.root/'clone.wav'
        run([executable('ffmpeg'),'-v','error','-y','-i',str(self.video),'-vn','-c:a','pcm_s16le',str(audio)],self.cancel)
        job=dict(video=str(self.video),audio=str(audio),source_srt=str(self.srt),target_srt=str(self.srt),output=str(self.root),language='ja',alignment='timed',trim=False,denoise=True,mute=True)
        f=Path(prepare(job,self.cancel));self.assertFalse((f/'video.mp4').exists());self.assertTrue((f/'subtitles.srt').exists())
        m=json.loads((f/'analysis.json').read_text());m['publish_settings']=dict(background=str(self.bg),title='本来の姿',cover_mode='frame',cover_time=.5)
        save_json(f/'analysis.json',m);self.assertTrue(Path(render_preview(f,2.5,self.cancel)).exists());self.assertFalse((f/'video.mp4').exists())
        render(f,self.cancel);self.assertTrue((f/'cover.png').exists())
        r=json.loads((f/'report.json').read_text());self.assertEqual(r['resolution'],[1080,1920]);self.assertEqual(r['speech_speed'],1.1)

if __name__=='__main__':unittest.main(verbosity=2)
