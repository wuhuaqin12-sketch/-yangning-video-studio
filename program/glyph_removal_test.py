import json,tempfile,threading,unittest,sys
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
import cv2
from glyph_removal import remove_frame,process
from project_vnext import defaults,normalize,file_digest
from sequence_vnext import ff,repair,layout_repair_key
from media import probe,Cancelled

class GlyphTests(unittest.TestCase):
    def test_changes_only_text_mask_at_different_positions(self):
        for width,height,y in [(480,270,210),(854,480,420)]:
            frame=np.full((height,width,3),160,np.uint8)
            cv2.rectangle(frame,(20,20),(width-20,45),(0,0,0),-1)
            cv2.putText(frame,'TEST',(width//3,y),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,0),6)
            cv2.putText(frame,'TEST',(width//3,y),cv2.FONT_HERSHEY_SIMPLEX,1,(255,255,255),2)
            roi=(width//3-10,y-32,120,40)
            fixed,mask=remove_frame(frame,roi)
            self.assertGreater(np.count_nonzero(mask),100)
            self.assertTrue(np.array_equal(fixed[mask==0],frame[mask==0]))
            self.assertTrue(np.array_equal(fixed[:100],frame[:100]))
            self.assertLess(np.count_nonzero(fixed>235),np.count_nonzero(frame>235)//2)
    def test_empty_caption_row_is_untouched(self):
        frame=np.full((180,320,3),155,np.uint8)
        result,mask=remove_frame(frame,(20,120,280,30))
        self.assertFalse(np.any(mask));self.assertTrue(np.array_equal(result,frame))
    def test_defaults_migration_and_method_invalidate_approval(self):
        p=defaults();self.assertEqual(p['layouts']['landscape']['subtitle_font_size'],'84')
        self.assertEqual(p['layouts']['portrait']['subtitle_font_size'],'')
        old=normalize({'layouts':{'landscape':{'repair_roi':'20,120,280,30','subtitle_font_size':'55'}}})
        self.assertEqual(old['layouts']['landscape']['repair_method'],'glyph')
        self.assertEqual(old['layouts']['landscape']['repair_approved'],'')
        self.assertEqual(old['layouts']['landscape']['subtitle_font_size'],'55')
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'source';f.write_bytes(b'original')
            q=p['layouts']['landscape'];q['repair_roi']='20,120,280,30'
            key=layout_repair_key(f,q);q['repair_method']='rectangle'
            with self.assertRaisesRegex(ValueError,'已移除'):layout_repair_key(f,q)
            q['repair_method']='glyph';q['repair_roi']='20,121,280,29'
            self.assertNotEqual(key,layout_repair_key(f,q))
    def test_real_stream_preserves_audio_timing_and_source_and_stops(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);source=folder/'source.mp4';cancel=threading.Event()
            image=np.full((180,320,3),155,np.uint8)
            cv2.putText(image,'TEST',(90,143),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,0,0),5)
            cv2.putText(image,'TEST',(90,143),cv2.FONT_HERSHEY_SIMPLEX,.7,(255,255,255),1)
            Image.fromarray(image[:,:,::-1]).save(folder/'source.png')
            ff(['-loop','1','-i',folder/'source.png','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1','-t',1,'-r',30,'-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',source],cancel)
            digest=file_digest(source);layout=defaults()['layouts']['landscape'];layout['repair_roi']='70,115,170,38'
            with self.assertRaisesRegex(ValueError,'确认'):repair(source,layout,folder,cancel)
            out=repair(source,layout,folder,cancel,preview=True,start=.2,length=.5)
            info=probe(out,cancel);streams=info['streams'];v=next(s for s in streams if s['codec_type']=='video')
            self.assertEqual((v['width'],v['height']),(320,180));self.assertTrue(any(s['codec_type']=='audio' for s in streams))
            self.assertAlmostEqual(float(info['format']['duration']),.5,delta=.06)
            record=json.loads(Path(out).with_suffix('.glyph.json').read_text(encoding='utf8'))
            self.assertEqual(record['frames'],15);self.assertGreater(record['changed_mask_pixels'],0)
            self.assertEqual(file_digest(source),digest)
            cancel.set()
            with self.assertRaises(Cancelled):process(source,folder/'cancel.mp4',v,(70,115,170,38),cancel,duration=.5)
            self.assertFalse((folder/'cancel.mp4').exists())
    def test_missing_dependency_never_falls_back(self):
        with patch.dict(sys.modules,{'cv2':None}):
            with self.assertRaisesRegex(RuntimeError,'不会回退'):process('missing','out',{},(0,0,1,1),threading.Event())

if __name__=='__main__':unittest.main()
