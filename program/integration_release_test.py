import json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from sequence_vnext import ff,concat_clips,cover_clip,preflight_assets
from mobile_video import inspect
from project_vnext import defaults
from ui_assets import check_image,remember_music,load_music

class IntegratedReleaseTests(unittest.TestCase):
    def test_cover_mixed_pixel_formats_are_normalized_to_mobile_avc_and_frames_advance(self):
        from media import probe,run,executable
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);stop=threading.Event();image=root/'cover.png';Image.new('RGB',(320,180),'blue').save(image)
            p=defaults();p.update(cover_seconds=2,cover_fit='contain')
            cover=cover_clip(image,'landscape',p,root,stop)
            body=root/'body.mp4'
            ff(['-f','lavfi','-i','color=green:s=1920x1080:r=30:d=1','-f','lavfi','-i','sine=frequency=660:duration=1','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv444p','-c:a','aac','-ar','48000','-ac','2',body],stop)
            out=root/'complete.mp4';concat_clips([cover,body],out,root,stop)
            q=inspect(out,stop);self.assertEqual(q['pixel_format'],'yuv420p');self.assertTrue(q['faststart']);self.assertFalse(q['device_playback_verified'])
            for at,channel in ((.3,2),(2.5,1)):
                frame=root/(str(at)+'.png');ff(['-ss',at,'-i',out,'-frames:v',1,frame],stop)
                pixel=np.array(Image.open(frame).convert('RGB'))[500,900];self.assertEqual(int(pixel.argmax()),channel)
            ff(['-xerror','-i',out,'-f','null','-'],stop)
    def test_default_music_remembers_explicit_choice_and_can_be_cleared(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'music.wav';p.write_bytes(b'path fixture')
            remember_music(root,p);self.assertEqual(load_music(root),str(p.resolve()))
            remember_music(root,'');self.assertEqual(load_music(root),'')
            self.assertEqual(p.read_bytes(),b'path fixture')
    def test_bad_cover_stops_before_alignment_and_input_is_not_changed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bad=root/'video.mp4';bad.write_bytes(b'not an image')
            with self.assertRaisesRegex(ValueError,'不能放入MP4'):check_image(bad,'封面')
            self.assertEqual(bad.read_bytes(),b'not an image')
    def test_runtime_directory_is_versioned_and_legacy_runtime_retained(self):
        from upgrade_guard import runtime_dir
        self.assertEqual(runtime_dir(Path('install'),'0.12.11'),Path('install/runtime'))
        self.assertEqual(runtime_dir(Path('install'),'0.14.0'),Path('install/runtimes/0.14.0'))
        self.assertNotEqual(runtime_dir(Path('install'),'0.14.0'),runtime_dir(Path('install'),'0.14.1'))
