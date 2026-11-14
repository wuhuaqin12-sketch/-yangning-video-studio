import json,tempfile,threading,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from project_vnext import defaults,save_project,load_project
from opening_caption import detect,localized_title,engine
from sequence_vnext import ff,compose_segment,concat_clips,process,seconds
from ending_card import append_card,overlay
from media import probe,executable

class DecorationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.cancel=threading.Event()
    def make_video(self,duration=1):
        im=Image.new('RGB',(640,360),'navy');draw=ImageDraw.Draw(im)
        font=ImageFont.truetype(str(Path(__file__).parent/'fonts/NotoSerifCJKjp-Regular.otf'),48)
        draw.text((145,90),'金刚经讲义',font=font,fill='white')
        image=self.root/'title.png';im.save(image);source=self.root/'title.mp4'
        ff(['-loop','1','-i',image,'-f','lavfi','-i',f'sine=frequency=440:duration={duration}','-t',duration,'-r',30,'-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',source],self.cancel)
        return source
    def test_real_local_ocr_places_translation_below_source_title(self):
        source=self.make_video()
        r=detect(source,'金刚经讲义',0,1,self.cancel)
        self.assertIn('金',r['recognized']);self.assertGreater(r['opening_title_y'],40)
        self.assertLess(r['opening_title_y'],70);self.assertGreater(r['opening_title_x'],35)
        self.assertLess(r['opening_title_x'],65)
        with self.assertRaisesRegex(ValueError,'未识别'):detect(source,'完全不同的标题',0,1,self.cancel)
    def test_languages_and_manual_title_and_persisted_optional_fields(self):
        self.assertIn('金剛経',localized_title('','ja'));self.assertIn('Diamond Sutra',localized_title('','en'))
        self.assertEqual(localized_title('','ja','经题'),'経題');self.assertEqual(localized_title('','en','经题'),'Title of the Sutra')
        self.assertEqual(localized_title('My title','en','其他标题'),'My title')
        with self.assertRaisesRegex(ValueError,'填写'):localized_title('','en','其他标题')
        p=defaults();p.update(opening_title_enabled=True,opening_title_text='Manual',disclaimer_enabled=True,disclaimer_image='missing.png',disclaimer_seconds=8,disclaimer_mode='overlay')
        f=self.root/'project.json';save_project(f,{'sequence':p});j,missing=load_project(f)
        self.assertEqual(j['sequence']['disclaimer_mode'],'overlay');self.assertIn('disclaimer_image',missing)
        self.assertEqual(j['sequence']['opening_title_text'],'Manual')
    def test_two_translated_titles_use_independent_multisecond_intervals(self):
        source=self.make_video(duration=9);p=defaults()
        p.update(opening_title_enabled=True,opening_title_start=.5,opening_title_end=5.5,opening_title_y=50,
                 opening_topic_enabled=True,opening_topic_start=6,opening_topic_end=8,opening_topic_y=65,_language='ja')
        out=compose_segment(source,[],{},'landscape',p,self.root,self.cancel,False,'opening')
        ass=(self.root/'opening_landscape.ass').read_text(encoding='utf-8-sig')
        self.assertIn('0:00:00.50,0:00:05.50,OpeningTranslated',ass)
        self.assertIn('0:00:06.00,0:00:08.00,OpeningTopicTranslated',ass)
        self.assertIn('経題',ass)
        for n,t in enumerate((.2,1,5,6.5,8.5)):
            frame=self.root/f'interval{n}.png';ff(['-ss',t,'-i',out,'-frames:v','1',frame],self.cancel)
            with Image.open(frame) as im:count=int(np.count_nonzero(np.all(np.asarray(im.convert('RGB'))[540:1000,250:1650]>210,axis=2)))
            if n in (0,4):self.assertLess(count,10)
            else:self.assertGreater(count,100)
        self.assertAlmostEqual(seconds(out,self.cancel),9,delta=.06)
    def test_title_is_real_overlay_and_keeps_audio_duration(self):
        source=self.make_video();p=defaults();p.update(opening_title_enabled=True,opening_title_start=.1,opening_title_end=.8,opening_title_y=50,_language='ja')
        out=compose_segment(source,[],{},'landscape',p,self.root,self.cancel,False,'opening')
        ass=(self.root/'opening_landscape.ass').read_text(encoding='utf-8-sig')
        self.assertIn('OpeningTranslated',ass);self.assertIn('金剛経',ass)
        info=probe(out,self.cancel);self.assertAlmostEqual(float(info['format']['duration']),1,delta=.06)
        frame=self.root/'frame.png';ff(['-ss',.5,'-i',out,'-frames:v','1',frame],self.cancel)
        with Image.open(frame) as im:
            a=np.asarray(im.convert('RGB'));self.assertGreater(np.count_nonzero(np.all(a[540:750,400:1500]>210,axis=2)),100)
    def test_disclaimer_append_preserves_whole_ending_and_overlay_preserves_music(self):
        source=self.make_video(duration=3);p=defaults()
        ending=compose_segment(source,[],{},'landscape',p,self.root,self.cancel,False,'ending')
        image=self.root/'disclaimer.png';Image.new('RGB',(100,100),'red').save(image)
        card=append_card(image,'landscape',2,self.root,self.cancel)
        joined=self.root/'joined.mp4';concat_clips([ending,card],joined,self.root,self.cancel)
        self.assertAlmostEqual(seconds(joined,self.cancel),5,delta=.1)
        frame=self.root/'last.png';ff(['-ss',4,'-i',joined,'-frames:v','1',frame],self.cancel)
        with Image.open(frame) as im:
            self.assertGreater(im.getpixel((960,540))[0],220);self.assertLess(im.getpixel((20,540))[0],20)
        annotated=overlay(ending,image,'landscape',2,self.root,self.cancel)
        self.assertAlmostEqual(seconds(annotated,self.cancel),3,delta=.08)
        def audio(path):return subprocess.check_output([executable('ffmpeg'),'-v','error','-i',str(path),'-map','0:a:0','-c','copy','-f','adts','-'])
        self.assertEqual(audio(annotated),audio(ending))
    def test_real_pipeline_keeps_srt_and_original_ending_before_appended_image(self):
        source=self.make_video();analysis=self.root/'analysis';analysis.mkdir()
        import shutil
        shutil.copyfile(source,analysis/'video.mp4');(analysis/'subtitles.srt').write_text('1\n00:00:00,100 --> 00:00:00,700\nテスト。\n',encoding='utf8')
        image=self.root/'notice.png';Image.new('RGB',(160,90),'red').save(image)
        p=defaults();p.update(output_mode='landscape',outro_enabled=True,outro_video=str(source),disclaimer_enabled=True,disclaimer_image=str(image),disclaimer_seconds=2)
        p['layouts']['landscape']['remove_chinese']=False
        job=dict(video=str(source),output=str(self.root/'outputs'),language='ja',sequence=p,burn=False,name='notice test')
        with patch('sequence_vnext.aligned',return_value=analysis):folder=Path(process(job,self.cancel))
        record=json.loads((folder/'report.json').read_text())
        self.assertAlmostEqual(record['results'][0]['duration'],4,delta=.15)
        self.assertTrue(Path(record['results'][0]['path']).with_suffix('.srt').exists())

if __name__=='__main__':unittest.main()
