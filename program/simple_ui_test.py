"""Regression checks for the simple one-click interface and workflow."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import workflow

class SimpleUITests(unittest.TestCase):
    def test_main_button_and_advanced_controls(self):
        src=Path(__file__).with_name('app.py').read_text(encoding='utf8')
        self.assertIn("text='一键生成视频',command=self.one_click_simple",src)
        self.assertIn("text='声音 / 停顿设置'",src)
        self.assertIn("label='项目'",src)
        self.assertIn("self.activity_open=False",src)
        self.assertIn("burn=False",src)
        self.assertIn("text='把新字幕写入视频画面'",src)
        self.assertNotIn("self.v['burn'].set(True)",src)
    def test_optional_audio_uses_source_audio(self):
        with TemporaryDirectory() as d:
            paths=[Path(d)/n for n in ('video.mp4','source.srt')]
            for p in paths:p.write_bytes(b'test')
            with patch.object(workflow,'LANGUAGES',{'ja'}):
                j=workflow.normalize(dict(video=str(paths[0]),audio='',source_srt=str(paths[1]),target_srt='',language='ja',alignment='auto',output=d))
            self.assertEqual(j['audio'],str(paths[0]))
            self.assertEqual(j['target_srt'],str(paths[1]))
            self.assertEqual(j['alignment'],'multi')

if __name__=='__main__':unittest.main()
