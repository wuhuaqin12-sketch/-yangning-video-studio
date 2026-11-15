import json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from media import parse_srt
from publish import make_ass
from project_vnext import defaults,file_digest
import sequence_vnext as seq

class LandscapeFixedTests(unittest.TestCase):
    def test_caption_length_never_changes_picture_box_and_preserves_every_cue(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);boxes=[]
            for text in ('短い字幕。','長い字幕を省略せず画面内で改行します。'*30):
                make_ass(root/'test.ass',[(1,1,21,text)],{'subtitle_font_size':64,'title':'','video_height':100},{'width':1920,'height':1080},22,1920,1080,auto_background=True,landscape_overlay=True,caption_row=(880,50))
                q=json.loads((root/'layout_report.json').read_text());boxes.append(q['video_box'])
                self.assertTrue(q['landscape_fixed_video']);self.assertFalse(q['auto_background'])
                self.assertLess(q['subtitle_box'][1],880);self.assertLessEqual(q['subtitle_box'][3],1080)
                self.assertEqual(q['caption_anchor'],'above_original_subtitle')
                cues=parse_srt(root/'publish_subtitles.srt')
                self.assertEqual(''.join(c[3].replace('\n','') for c in cues),text)
                self.assertEqual((cues[0][1],cues[-1][2]),(1,21))
                self.assertTrue(all(len(c[3].splitlines())<=5 for c in cues))
                self.assertTrue(all(44<=v<=64 for v in q['subtitle_actual_px']))
            self.assertEqual(boxes,[[0,0,1920,1080]]*2)
    def test_source_aspect_and_vertical_layout_are_retained(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);make_ass(root/'t.ass',[(1,0,5,'字幕')],{'title':'','video_height':100},{'width':1440,'height':1080},5,1920,1080,landscape_overlay=True)
            q=json.loads((root/'layout_report.json').read_text());self.assertEqual(q['video_box'],[240,0,1440,1080])
            make_ass(root/'v.ass',[(1,0,5,'字幕')],{'title':'','video_height':76,'subtitle_area':'below_video'},{'width':1920,'height':1080},5,1080,1920,landscape_overlay=False)
            q=json.loads((root/'layout_report.json').read_text());x,y,w,h=q['video_box']
            self.assertEqual(q['subtitle_area'],'below_video');self.assertGreater(q['subtitle_box'][1],y+h)
    def test_render_long_caption_preserves_full_frame(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cancel=threading.Event();source=root/'source.mp4'
            seq.ff(['-f','lavfi','-i','color=red:s=320x180:r=30:d=0.8','-f','lavfi','-i','sine=frequency=440:duration=0.8','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',source],cancel)
            before=file_digest(source);p=defaults();p['layouts']['landscape'].update(remove_chinese=False,repair_roi='0,145,320,20')
            dest=seq.compose_segment(str(source),[(1,0,.8,'長い字幕でも先生の画面を縮小せず原字幕の上から下へ表示します。'*5)],{},'landscape',p,root,cancel,True,'body')
            q=json.loads((root/'body_landscape.layout.json').read_text());self.assertEqual(q['video_box'],[0,0,1920,1080])
            image=root/'frame.png';seq.ff(['-ss',.3,'-i',dest,'-frames:v',1,image],cancel)
            with Image.open(image) as im:
                for xy in ((240,140),(1680,140),(240,940),(1680,940),(960,300)):
                    r,g,b=im.convert('RGB').getpixel(xy);self.assertGreater(r,210);self.assertLess(g,30);self.assertLess(b,30)
            self.assertEqual(before,file_digest(source))
