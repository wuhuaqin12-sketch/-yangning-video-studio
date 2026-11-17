import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from ending_presets import save_preset,load_preset

class PresetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        mock=patch('media.probe',return_value={'streams':[{'codec_type':'video'}]});mock.start();self.addCleanup(mock.stop)
    def test_six_languages_are_independent_and_survive_source_move(self):
        for code in ('ja','en','fr','de','yue','id'):
            source=self.root/(code+'.mp4');source.write_bytes(code.encode());saved=save_preset(self.root/'presets',code,source);source.unlink()
            self.assertEqual(load_preset(self.root/'presets',code),saved);self.assertEqual(saved.read_bytes(),code.encode())
            self.assertNotIn('combined_outro_start',json.loads((saved.parent/'preset.json').read_text()))
        self.assertIsNone(load_preset(self.root/'presets','es'))
    def test_modified_or_missing_copy_fails_without_fallback(self):
        source=self.root/'source.mp4';source.write_bytes(b'ja');saved=save_preset(self.root/'presets','ja',source);saved.write_bytes(b'en')
        with self.assertRaisesRegex(ValueError,'变化'):load_preset(self.root/'presets','ja')
        saved.unlink()
        with self.assertRaisesRegex(ValueError,'丢失'):load_preset(self.root/'presets','ja')
    def test_ambiguous_or_unsafe_language_is_rejected(self):
        for code in ('other','auto','','../ja'):
            with self.assertRaises(ValueError):load_preset(self.root,code)
    def test_nonvideo_cannot_replace_preset(self):
        source=self.root/'source.mp4';source.write_bytes(b'ja');save_preset(self.root/'presets','ja',source)
        with patch('media.probe',return_value={'streams':[{'codec_type':'audio'}]}):
            with self.assertRaisesRegex(ValueError,'画面'):save_preset(self.root/'presets','ja',source)
        self.assertEqual(load_preset(self.root/'presets','ja').read_bytes(),b'ja')

class DiamondGateTests(unittest.TestCase):
    def test_disabled_group_keeps_values_but_does_not_process_them(self):
        from types import SimpleNamespace
        from next_ui import SequencePanel,SEGMENT_MODES
        from project_vnext import defaults
        class Var:
            def __init__(self,value):self.value=value
            def get(self):return self.value
        p=defaults();p.update(combined_outro_start=120,combined_replace_outro=True,opening_title_enabled=True,background_audio='ja.wav')
        panel=SimpleNamespace(v={k:Var(v) for k,v in p.items() if k!='layouts'},layout_vars={m:{k:Var(v) for k,v in layout.items() if k!='style'} for m,layout in p['layouts'].items()},layout_styles={m:{} for m,layout in p['layouts'].items()},segment_mode=Var(SEGMENT_MODES[0]))
        panel.raw_value=lambda:SequencePanel.raw_value(panel)
        off=SequencePanel.value(panel)
        self.assertFalse(off['combined']);self.assertFalse(off['combined_replace_outro']);self.assertTrue(off['opening_title_enabled']);self.assertEqual(off['background_audio'],'')
        self.assertEqual(panel.v['combined_outro_start'].get(),120)
        panel.segment_mode.value=SEGMENT_MODES[2];on=SequencePanel.value(panel)
        self.assertTrue(on['combined']);self.assertTrue(on['combined_replace_outro']);self.assertTrue(on['opening_title_enabled']);self.assertEqual(on['combined_outro_start'],120)
