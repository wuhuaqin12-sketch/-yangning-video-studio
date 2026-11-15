import json,tempfile,threading,unittest
from pathlib import Path
from PIL import Image
from publish import make_ass
from project_vnext import defaults,file_digest
from style_preview import render
from sequence_vnext import ff

class BackgroundLayoutTests(unittest.TestCase):
    def test_saved_height_preserves_borders_and_title_is_above_teacher(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);boxes=[]
            for text in ('字幕','字幕を省略せず自動改行します。'*30):
                make_ass(root/'t.ass',[(1,0,20,text)],dict(title='金剛経',title_font='Yuji Boku',title_y=25,video_height=76,subtitle_font_size=64),dict(width=1920,height=1080),20,1920,1080,landscape_overlay=True,title_in_top_background=True)
                q=json.loads((root/'layout_report.json').read_text());boxes.append(q['video_box'])
                self.assertEqual(q['video_box'],[231,130,1458,820])
                self.assertGreater(q['title_center'][1],27);self.assertLess(q['title_center'][1],130)
                self.assertLess(q['title_actual_px'],q['title_requested_px'])
            self.assertEqual(boxes[0],boxes[1])
    def test_custom_height_is_used_and_full_frame_title_never_covers_teacher(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            make_ass(root/'c.ass',[(1,0,1,'字幕')],dict(title='',video_height=60),dict(width=1920,height=1080),1,1920,1080,landscape_overlay=True)
            q=json.loads((root/'layout_report.json').read_text());self.assertEqual(q['video_box'],[384,216,1152,648])
            with self.assertRaisesRegex(ValueError,'上方背景不足'):
                make_ass(root/'no.ass',[(1,0,1,'字幕')],dict(title='金剛経',video_height=100),dict(width=1920,height=1080),1,1920,1080,landscape_overlay=True,title_in_top_background=True)
    def test_shared_preview_has_background_title_and_correct_ratio(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);stop=threading.Event();source=root/'body.mp4';bg=root/'background.png'
            Image.new('RGB',(320,180),'blue').save(bg)
            ff(['-f','lavfi','-i','color=red:s=320x180:r=30:d=1','-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',source],stop)
            srt=root/'body.srt';srt.write_text('1\n00:00:00,100 --> 00:00:00,800\n字幕\n',encoding='utf8')
            before=file_digest(source);settings=dict(video=str(source),srt=str(srt),background=str(bg),output=str(root/'out'),preview_time=.2,title='金剛経',title_font='Yuji Boku',title_color='#FFD700',video_height=76,subtitle_font_size=48)
            for mode,size in [('landscape',(1920,1080)),('portrait',(1080,1920))]:
                image=Path(render(settings,defaults(),mode,stop))
                with Image.open(image) as im:
                    self.assertEqual(im.size,size)
                    r,g,b=im.convert('RGB').getpixel((10,10))
                    if mode=='portrait':self.assertGreater(b,200);self.assertLess(r,30)
                    else:self.assertGreater(r,200);self.assertLess(b,30)
                q=json.loads((image.parent/('body_'+mode+'.layout.json')).read_text())
                if mode=='portrait':self.assertLess(q['title_center'][1],q['video_box'][1])
                else:self.assertIsNone(q['title_center']);self.assertEqual(q['video_box'],[0,0,1920,1080])
                self.assertEqual(q['subtitle_requested_px'],48)
                scope=json.loads((image.parent/'preview_scope.json').read_text());self.assertFalse(scope['full_export']);self.assertFalse(scope['speech_alignment'])
            self.assertEqual(file_digest(source),before)

    def test_landscape_ignores_stale_background_title_geometry_and_keeps_silent_non_wide_source(self):
        from sequence_vnext import compose_segment,seconds
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);stop=threading.Event();source=root/'four_three.mp4'
            ff(['-f','lavfi','-i','color=red:s=320x240:r=30:d=0.4','-c:v','libx264','-pix_fmt','yuv420p',source],stop)
            p=defaults();p['background']=str(root/'missing_old_background.png')
            p['layouts']['landscape']['style']={'title':'OLD TITLE','video_width':40,'video_height':40}
            result=compose_segment(str(source),[],{'title':'金剛経','video_height':76},'landscape',p,root,stop,False,'body')
            q=json.loads((root/'body_landscape.layout.json').read_text())
            self.assertEqual(q['video_box'],[240,0,1440,1080]);self.assertIsNone(q['title_center'])
            self.assertAlmostEqual(seconds(result,stop),.4,delta=.08)
            self.assertEqual(sum(s['codec_type']=='audio' for s in __import__('media').probe(result,stop)['streams']),1)
