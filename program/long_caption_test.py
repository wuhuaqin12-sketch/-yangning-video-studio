"""Regression: overflow captions export at one size without losing text."""
import json,re,tempfile,threading,unittest
from pathlib import Path
from publish import make_ass,compose
from media import parse_srt,run,executable,probe

class LongCaptionTests(unittest.TestCase):
    def test_pages_preserve_text_colour_size_and_bounds(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            for size in (47,30):
                for font,text in [('Noto Serif CJK JP',('本当の自由と無我を理解する。'*80)),
                                  ('DejaVu Sans',('When an angel falls into hell, how can they hold on to their purity and goodness? '*35))]:
                    make_ass(p/'publish.ass',[(1,2,32,text)],dict(subtitle_font_size=size,font=font,keywords='無我=#E53935'),{'width':854,'height':480},33,1080,1920)
                    report=json.loads((p/'layout_report.json').read_text())
                    self.assertEqual(report['subtitle_actual_px'],[size])
                    self.assertEqual(report['split_cues'],[1])
                    cues=parse_srt(p/'publish_subtitles.srt')
                    self.assertAlmostEqual(cues[0][1],2)
                    self.assertAlmostEqual(cues[-1][2],32)
                    self.assertEqual(re.sub(r'\s','',text),re.sub(r'\s','',''.join(x[3] for x in cues)))
                    self.assertTrue(all(a[2]==b[1] for a,b in zip(cues,cues[1:])))
                    self.assertTrue(all(x[2]>x[1] for x in cues))
                    if font=='Noto Serif CJK JP':self.assertIn(r'\1c&H3539E5&',(p/'publish.ass').read_text())
    def test_actual_long_caption_export(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);cancel=threading.Event()
            run([executable('ffmpeg'),'-v','error','-y','-f','lavfi','-i','color=c=gray:size=320x180:rate=10:duration=3','-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','libx264','-threads','2','-c:a','aac','-shortest',str(p/'in.mp4')],cancel)
            Image.new('RGB',(540,960),'beige').save(p/'bg.png')
            (p/'in.srt').write_text('1\n00:00:00,000 --> 00:00:03,000\n'+('When an angel falls into hell, how can they keep their purity and goodness? '*12)+'\n')
            out=Path(compose(dict(video=str(p/'in.mp4'),srt=str(p/'in.srt'),background=str(p/'bg.png'),output=str(p/'out')),cancel))
            self.assertTrue(out.is_file())
            self.assertGreater(len(parse_srt(out.parent/'publish_subtitles.srt')),1)
            self.assertAlmostEqual(float(probe(out,cancel)['format']['duration']),3,delta=.16)
            print('LONG_CAPTION_EXPORT_PASS',out)

if __name__=='__main__':unittest.main(verbosity=2)
