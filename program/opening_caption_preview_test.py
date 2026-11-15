import json,tempfile,threading,unittest,wave
from pathlib import Path
import numpy as np
from PIL import Image
from media import run,executable,Cancelled,probe
from project_vnext import defaults,file_digest
from opening_caption_preview import render

class TitlePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);cls.stop=threading.Event();cls.source=cls.root/'source.mp4'
        run([executable('ffmpeg'),'-nostdin','-v','error','-y','-f','lavfi','-i','color=navy:s=640x360:r=10:d=20','-f','lavfi','-i','sine=frequency=440:duration=20','-c:v','libx264','-preset','fast','-pix_fmt','yuv420p','-c:a','aac',str(cls.source)],cls.stop)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_selected_second_title_renders_without_outro_audio_srt_or_other_title(self):
        p=defaults();p.update(combined=True,combined_outro_start=0,outro_video='missing.mp4',opening_title_end=0,opening_topic_start=5,opening_topic_end=7,opening_topic_text='SECOND TITLE',opening_topic_y=70,opening_topic_color='#FFFFFF')
        before=file_digest(self.source)
        out=Path(render(self.source,p,'en','opening_topic',self.root,self.stop))
        ass=(out.parent/'title_preview.ass').read_text(encoding='utf-8-sig')
        self.assertIn('0:00:00.50,0:00:02.50,OpeningTopicTranslated',ass);self.assertIn('SECOND TITLE',ass)
        self.assertAlmostEqual(float(probe(out,self.stop)['format']['duration']),3,delta=.08)
        frame=out.parent/'frame.png';run([executable('ffmpeg'),'-nostdin','-v','error','-y','-ss','1','-i',str(out),'-frames:v','1',str(frame)],self.stop)
        with Image.open(frame) as im:self.assertGreater(np.count_nonzero(np.all(np.asarray(im.convert('RGB'))[220:330]>200,axis=2)),20)
        pcm=out.parent/'audio.wav';run([executable('ffmpeg'),'-nostdin','-v','error','-y','-i',str(out),'-t','1','-ar','16000','-ac','1','-c:a','pcm_s16le',str(pcm)],self.stop)
        with wave.open(str(pcm)) as wav:samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2')
        peak=np.argmax(np.abs(np.fft.rfft(samples)));frequency=peak*16000/len(samples)
        self.assertAlmostEqual(frequency,440,delta=3);self.assertEqual(file_digest(self.source),before)
        scope=json.loads((out.parent/'preview_scope.json').read_text());self.assertFalse(scope['full_preview_approved']);self.assertFalse(scope['ending'])
    def test_long_interval_is_bounded_to_fifteen_seconds(self):
        p=dict(opening_title_start=0,opening_title_end=20,opening_title_text='TITLE',opening_title_y=60)
        out=Path(render(self.source,p,'en','opening_title',self.root,self.stop))
        self.assertAlmostEqual(float(probe(out,self.stop)['format']['duration']),15,delta=.08)
    def test_out_of_range_and_cancel_are_explicit(self):
        with self.assertRaisesRegex(ValueError,'超出'):render(self.source,{'opening_title_start':25,'opening_title_end':30},'en','opening_title',self.root,self.stop)
        cancelled=threading.Event();cancelled.set()
        with self.assertRaises(Cancelled):render(self.source,{},'en','opening_title',self.root,cancelled)
