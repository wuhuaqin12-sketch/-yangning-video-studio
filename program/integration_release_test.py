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

    def test_previous_version_restores_matching_settings_without_touching_media(self):
        from desktop_update import atomic_json
        from stable_recovery import snapshot
        from upgrade_guard import rollback_previous
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'install';settings=Path(d)/'settings';settings.mkdir()
            old=root/'versions/0.12.11/program';old.mkdir(parents=True);(old/'app.py').write_text('# old program')
            atomic_json(root/'current.json',{'version':'0.12.11'})
            atomic_json(settings/'style_no_denoise.json',{'title':'old'})
            saved=snapshot(root,settings)
            atomic_json(root/'protected/pre-upgrade-0.14.0.json',{'backup':str(saved)})
            atomic_json(root/'current.json',{'version':'0.14.0','previous_version':'0.12.11'})
            atomic_json(settings/'style_no_denoise.json',{'title':'new'})
            media=settings/'my_video.mp4';media.write_bytes(b'keep')
            self.assertEqual(rollback_previous(root,settings),'0.12.11')
            self.assertEqual(json.loads((settings/'style_no_denoise.json').read_text())['title'],'old')
            self.assertEqual(media.read_bytes(),b'keep')
            self.assertEqual(json.loads((root/'current.json').read_text())['version'],'0.12.11')
    def test_bad_backup_does_not_change_current_program_or_settings(self):
        from desktop_update import atomic_json
        from stable_recovery import snapshot
        from upgrade_guard import rollback_previous
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'install';settings=Path(d)/'settings';settings.mkdir()
            atomic_json(root/'current.json',{'version':'0.12.11'})
            atomic_json(settings/'style_no_denoise.json',{'title':'old'})
            saved=snapshot(root,settings)
            atomic_json(root/'protected/pre-upgrade-0.14.0.json',{'backup':str(saved)})
            atomic_json(root/'current.json',{'version':'0.14.0','previous_version':'0.12.11'})
            atomic_json(saved/'settings/style_no_denoise.json',{'title':'damaged'})
            with self.assertRaisesRegex(ValueError,'校验失败'):rollback_previous(root,settings)
            self.assertEqual(json.loads((root/'current.json').read_text())['version'],'0.14.0')
            self.assertEqual(json.loads((settings/'style_no_denoise.json').read_text())['title'],'old')
