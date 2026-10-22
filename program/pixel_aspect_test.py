import json,tempfile,threading,unittest
from pathlib import Path
from PIL import Image
from engine import prepare,render,render_preview,square_pixel_stream
from media import run,probe,executable,parse_srt
class PixelAspectTests(unittest.TestCase):
    def test_sar_exports(self):
        for sar,width in [('4/3',160),('3/4',90),('1/1',120),('1001/1000',120)]:
            with self.subTest(sar=sar),tempfile.TemporaryDirectory() as d:
                p=Path(d);c=threading.Event();ff=executable('ffmpeg')
                run([ff,'-v','error','-y','-f','lavfi','-i','testsrc2=size=120x160:rate=10:duration=2','-vf','setsar='+sar,'-c:v','libx264',str(p/'input.mp4')],c)
                run([ff,'-v','error','-y','-f','lavfi','-i','sine=frequency=440:sample_rate=16000:duration=2',str(p/'audio.wav')],c)
                (p/'text.srt').write_text('1\n00:00:00,000 --> 00:00:01,900\nPixel ratio test\n')
                job=dict(video=str(p/'input.mp4'),audio=str(p/'audio.wav'),source_srt=str(p/'text.srt'),target_srt=str(p/'text.srt'),output=str(p/'out'),language='en',alignment='timed',trim=False,burn=True)
                before=(p/'input.mp4').read_bytes();folder=Path(prepare(job,c))
                with Image.open(render_preview(folder,.5,c)) as image:self.assertEqual(image.size,(width,160))
                render(folder,c);info=probe(folder/'video.mp4',c);v=next(s for s in info['streams'] if s['codec_type']=='video')
                self.assertEqual((v['width'],v['height']),(width,160));self.assertIn(v.get('sample_aspect_ratio'),(None,'1:1'))
                self.assertAlmostEqual(float(info['format']['duration']),2,delta=.15)
                self.assertEqual(parse_srt(folder/'subtitles.srt')[0][3],'Pixel ratio test')
                self.assertEqual((p/'input.mp4').read_bytes(),before)
                self.assertTrue(json.loads((folder/'report.json').read_text())['full_decode_passed'])
                if sar=='4/3':
                    bg=p/'bg.png';Image.new('RGB',(108,192),'beige').save(bg)
                    metadata=json.loads((folder/'analysis.json').read_text())
                    metadata['publish_settings']=dict(background=str(bg),title='本来の姿',cover_mode='frame',cover_time=.5)
                    (folder/'analysis.json').write_text(json.dumps(metadata))
                    with Image.open(render_preview(folder,.5,c)) as image:self.assertEqual(image.size,(1080,1920))
                    render(folder,c)
                    self.assertTrue((folder/'cover.png').exists())
                    self.assertEqual(json.loads((folder/'report.json').read_text())['resolution'],[1080,1920])
    def test_invalid_ratio(self):
        for value in ('bad','-1:1','1:0'):
            with self.subTest(value=value),self.assertRaises(ValueError):square_pixel_stream(dict(width=120,height=160,sample_aspect_ratio=value))
if __name__=='__main__':unittest.main(verbosity=2)
