"""Pixel-level check: first caption line remains near the teacher's lower edge."""
import unittest,tempfile,threading,json,subprocess
from pathlib import Path
import numpy as np
from PIL import Image
from sequence_vnext import compose_segment,ff
from project_vnext import defaults

class CaptionTopTests(unittest.TestCase):
    def test_first_line_top_anchor_for_short_and_multiline_captions(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cancel=threading.Event();source=root/'gray.mp4'
            ff(['-f','lavfi','-i','color=gray:size=854x480:rate=30:duration=3','-f','lavfi','-i','anullsrc=r=48000:cl=stereo:d=3','-c:v','libx264','-c:a','aac',source],cancel)
            phrase='字幕の位置を確認します。'
            cues=[(1,0,1,phrase),(2,1,2,phrase*2),(3,2,3,phrase*6)]
            out=compose_segment(str(source),cues,{'subtitle_font_size':70},'portrait',defaults(),root,cancel,True,'body')
            report=json.loads((root/'layout_report.json').read_text(encoding='utf8'));vx,vy,vw,vh=report['video_box'];edge=vy+vh
            tops=[]
            for i,t in enumerate((.5,1.5,2.5)):
                dest=root/f'frame{i}.png';ff(['-ss',t,'-i',out,'-frames:v','1',dest],cancel)
                with Image.open(dest) as im:arr=np.array(im.convert('RGB'))
                mask=np.all(arr[edge+1:1728,80:1000]>220,axis=2);ys=np.where(mask)[0];self.assertGreater(len(ys),20)
                top=edge+1+int(ys.min());tops.append(top)
                self.assertGreater(top,edge+8);self.assertLess(top,edge+80)
            self.assertLessEqual(max(tops)-min(tops),4)
            ass=(root/'body_portrait.ass').read_text(encoding='utf-8-sig');self.assertIn(r'\an8\pos(',ass)
if __name__=='__main__':unittest.main()
