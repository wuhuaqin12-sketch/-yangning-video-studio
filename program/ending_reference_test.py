import json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw
from media import run,executable,Cancelled,probe
import ending_reference as e

class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);cls.stop=threading.Event()
        def pattern(name,color,phase,seconds):
            image=Image.new('RGB',(192,108),color);draw=ImageDraw.Draw(image)
            for i in range(6):
                x=(i*29+phase*17)%170;draw.rectangle((x,12+i*12,x+15,18+i*12),fill=('white' if i%2 else 'gold'))
            draw.ellipse((60+phase*3,22,120,84),outline='orange',width=4)
            path=cls.root/(name+'.png');image.save(path);out=path.with_suffix('.mp4')
            run([executable('ffmpeg'),'-nostdin','-v','error','-y','-loop','1','-i',str(path),'-t',str(seconds),'-r','24','-c:v','libx264','-pix_fmt','yuv420p',str(out)],cls.stop);return out
        cls.body=pattern('body','white',1,4);cls.long_body=pattern('long_body','gray',2,7)
        cls.a=pattern('a','navy',0,1);cls.b=pattern('b','darkgreen',1,1);cls.c=pattern('c','maroon',2,1)
        cls.ref=cls.join('ref',[cls.a,cls.b,cls.c]);cls.full=cls.join('full',[cls.body,cls.ref]);cls.long=cls.join('long',[cls.long_body,cls.ref])
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    @classmethod
    def join(cls,name,clips):
        listing=cls.root/(name+'.txt');listing.write_text(''.join("file '"+str(p).replace('\\','/')+"'\n" for p in clips));out=cls.root/(name+'.mp4')
        run([executable('ffmpeg'),'-nostdin','-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-c','copy',str(out)],cls.stop);return out
    def setUp(self):
        self.local=tempfile.TemporaryDirectory();self.addCleanup(self.local.cleanup);self.store=Path(self.local.name)
        e.save_reference(self.store,self.ref,0,self.stop)
    def test_different_body_lengths_find_their_own_boundary_and_preview(self):
        for source,expected in ((self.full,4),(self.long,7)):
            before=e.digest(source);result=e.detect(self.store,source,self.stop)
            self.assertAlmostEqual(result['start'],expected,delta=.13);self.assertGreater(result['score'],.93)
            rendered=e.preview(self.store,source,result,result['start'],self.stop)
            self.assertTrue(Path(rendered['path']).is_file());self.assertEqual(e.digest(source),before)
    def test_current_full_video_can_register_only_its_confirmed_tail(self):
        data=e.save_reference(self.store,self.full,4,self.stop)
        self.assertAlmostEqual(data['seconds'],3,delta=.1)
        self.assertAlmostEqual(e.detect(self.store,self.long,self.stop)['start'],7,delta=.13)
    def test_wrong_reference_and_duplicate_tail_are_not_applied(self):
        wrong=self.join('wrong',[self.body,self.body])
        with self.assertRaisesRegex(ValueError,'可靠|唯一|较长'):e.detect(self.store,wrong,self.stop)
        duplicate=self.join('duplicate',[self.body,self.ref,self.ref])
        with self.assertRaisesRegex(ValueError,'唯一'):e.detect(self.store,duplicate,self.stop)
    def test_black_reference_rejected_without_destroying_previous_reference(self):
        black=self.root/'black.mp4'
        run([executable('ffmpeg'),'-nostdin','-v','error','-y','-f','lavfi','-i','color=black:s=192x108:r=24:d=3','-c:v','libx264',str(black)],self.stop)
        before=e.metadata(self.store)
        with self.assertRaisesRegex(ValueError,'单一|纯黑'):e.save_reference(self.store,black,0,self.stop)
        self.assertEqual(e.metadata(self.store),before)
    def test_changed_source_or_reference_invalidates_candidate(self):
        candidate=e.detect(self.store,self.full,self.stop)
        with self.assertRaisesRegex(ValueError,'视频已'):e.check_candidate(self.store,self.long,candidate)
        e.save_reference(self.store,self.join('other_ref',[self.c,self.b,self.a]),0,self.stop)
        with self.assertRaisesRegex(ValueError,'参考已'):e.check_candidate(self.store,self.full,candidate)
    def test_missing_corrupt_and_cancelled_are_explicit(self):
        path,data=e.load_reference(self.store);path.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'丢失|变化'):e.detect(self.store,self.full,self.stop)
        e.save_reference(self.store,self.ref,0,self.stop)
        cancel=threading.Event();cancel.set()
        with self.assertRaises(Cancelled):e.detect(self.store,self.full,cancel)
