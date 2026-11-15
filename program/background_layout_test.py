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
    def test_default_landscape_uses_original_row_and_offsets_preserve_text_bounds(self):
        from media import parse_srt
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);boxes=[];tops=[];text='長い字幕を省略しません。'*20
            for offset in (0,60,-60,400,-400):
                make_ass(root/'a.ass',[(1,1,21,text)],dict(title='',video_height=100,subtitle_font_size=48,subtitle_offset_y=offset),dict(width=1920,height=1080),22,1920,1080,landscape_overlay=True,caption_row=(880,60))
                q=json.loads((root/'layout_report.json').read_text());boxes.append(q['video_box']);tops.append(q['subtitle_box'][1])
                self.assertAlmostEqual(q['subtitle_offset_applied_px'],tops[-1]-880,delta=.01)
                self.assertLess(q['subtitle_box'][3],1080)
                cues=__import__('media').parse_srt(root/'publish_subtitles.srt')
                self.assertEqual(''.join(c[3].replace('\n','') for c in cues),text)
                self.assertEqual((cues[0][1],cues[-1][2]),(1,21))
            self.assertEqual(boxes,[[0,0,1920,1080]]*5);self.assertEqual(tops[:3],[880,940,820])
            self.assertLess(tops[3]-tops[0],400);self.assertGreaterEqual(tops[4],1080*.55)
    def test_ratio_offsets_survive_style_roundtrip_and_legacy_migration(self):
        from publish_style import normalize_style,save_preset,load_preset
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'style.json';save_preset(p,dict(landscape_subtitle_offset_y=60,portrait_subtitle_offset_y=20))
            q=load_preset(p);self.assertEqual((q['landscape_subtitle_offset_y'],q['portrait_subtitle_offset_y']),(60,20))
            q=normalize_style(dict(subtitle_offset_y=30));self.assertEqual((q['landscape_subtitle_offset_y'],q['portrait_subtitle_offset_y']),(30,30))
            for value in ('bad',float('nan'),401):
                with self.assertRaises(ValueError):normalize_style(dict(landscape_subtitle_offset_y=value))
    def test_shared_export_and_preview_use_separate_offsets_not_hidden_zero(self):
        from sequence_vnext import compose_segment
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);stop=threading.Event();source=root/'source.mp4';srt=root/'source.srt'
            ff(['-f','lavfi','-i','color=red:s=320x180:r=30:d=0.4','-c:v','libx264','-pix_fmt','yuv420p',source],stop)
            srt.write_text('1\n00:00:00,000 --> 00:00:00,400\n字幕\n',encoding='utf8')
            p=defaults();p['layouts']['landscape']['repair_roi']='0,145,320,20'
            settings=dict(video=str(source),srt=str(srt),output=str(root),preview_time=0,title='',subtitle_font_size=48,landscape_subtitle_offset_y=40,portrait_subtitle_offset_y=20)
            image=Path(render(settings,p,'landscape',stop))
            preview=json.loads((image.parent/'body_landscape.layout.json').read_text())
            out=root/'export';out.mkdir();compose_segment(str(source),[(1,0,.4,'字幕')],settings,'landscape',p,out,stop,True,'body')
            exported=json.loads((out/'body_landscape.layout.json').read_text())
            self.assertEqual(preview['subtitle_box'],exported['subtitle_box']);self.assertEqual(exported['subtitle_offset_requested_px'],40);self.assertEqual(exported['subtitle_offset_applied_px'],40)
            out2=root/'portrait';out2.mkdir();compose_segment(str(source),[(1,0,.4,'字幕')],settings,'portrait',p,out2,stop,True,'body')
            vertical=json.loads((out2/'body_portrait.layout.json').read_text());self.assertEqual(vertical['subtitle_offset_requested_px'],20)
            self.assertGreater(vertical['subtitle_box'][1],sum(vertical['video_box'][1::2]))
    def test_manual_landscape_sizes_are_not_capped_or_shrunk_and_text_survives(self):
        from media import parse_srt
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);text='長い字幕を省略せず表示します。'*20
            for size in (50,80,100,200):
                make_ass(root/'a.ass',[(1,1,31,text)],dict(title='',video_height=100,subtitle_font_size=size),dict(width=1920,height=1080),32,1920,1080,landscape_overlay=True,caption_row=(880,60))
                q=json.loads((root/'layout_report.json').read_text());self.assertEqual(q['subtitle_requested_px'],size);self.assertEqual(q['subtitle_actual_px'],[size]);self.assertEqual(q['video_box'],[0,0,1920,1080])
                self.assertFalse(q['shrunk_cues']);self.assertGreaterEqual(q['subtitle_box'][1],1080*.55)
                cues=parse_srt(root/'publish_subtitles.srt');self.assertEqual(''.join(c[3].replace('\n','') for c in cues),text);self.assertEqual((cues[0][1],cues[-1][2]),(1,31))
            with self.assertRaisesRegex(ValueError,'不会自动缩小'):
                make_ass(root/'too_big.ass',[(1,0,5,'字幕')],dict(title='',video_height=100,subtitle_font_size=480),dict(width=1920,height=1080),5,1920,1080,landscape_overlay=True)
    def test_real_rendered_glyph_height_increases_with_landscape_setting(self):
        from sequence_vnext import compose_segment
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);stop=threading.Event();source=root/'source.mp4'
            ff(['-f','lavfi','-i','color=red:s=320x180:r=30:d=0.4','-c:v','libx264','-pix_fmt','yuv420p',source],stop)
            heights=[]
            for size in (50,80,100,200):
                out=root/str(size);out.mkdir()
                v=compose_segment(str(source),[(1,0,.4,'字幕')],dict(title='',subtitle_font_size=64,landscape_subtitle_font_size=size,portrait_subtitle_font_size=70),'landscape',defaults(),out,stop,True,'body')
                q=json.loads((out/'body_landscape.layout.json').read_text());self.assertEqual(q['subtitle_actual_px'],[size]);self.assertEqual(q['subtitle_requested_px'],size)
                image=out/'frame.png';ff(['-i',v,'-frames:v',1,image],stop)
                a=np.array(Image.open(image).convert('RGB'));ys,xs=np.where(np.all(a>200,axis=2));self.assertGreater(len(ys),20);heights.append(int(ys.max()-ys.min()+1))
            self.assertTrue(all(a<b for a,b in zip(heights,heights[1:])));self.assertGreater(heights[-1],heights[2]*1.7)
    def test_ratio_font_sizes_save_independently_and_migrate_old_shared_value(self):
        from publish_style import normalize_style,save_preset,load_preset
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'style.json';save_preset(path,dict(landscape_subtitle_font_size=120,portrait_subtitle_font_size=70));q=load_preset(path)
            self.assertEqual((q['landscape_subtitle_font_size'],q['portrait_subtitle_font_size']),(120,70))
            q=normalize_style(dict(subtitle_font_size=100));self.assertEqual((q['landscape_subtitle_font_size'],q['portrait_subtitle_font_size']),(100,100))
            for val in ('bad',float('nan'),500):
                with self.assertRaises(ValueError):normalize_style(dict(landscape_subtitle_font_size=val))
