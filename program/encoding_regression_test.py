"""Regressions for Japanese Windows locale-independent internal text files."""
import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
import bootstrap
from engine import save_json

class EncodingTests(unittest.TestCase):
    def test_production_text_files_declare_encoding(self):
        for name in ('engine', 'app', 'media', 'multilingual', 'workflow', 'audio_edit', 'bootstrap'):
            tree = ast.parse(Path(__file__).with_name(name+'.py').read_text(encoding='utf8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in ('read_text', 'write_text'):
                        self.assertTrue(any(k.arg == 'encoding' for k in node.keywords), (name, node.lineno))

    def test_json_preserves_multilingual_paths(self):
        original = Path.read_text
        def cp932_read(path, encoding=None, errors=None):
            return original(path, encoding=encoding or 'cp932', errors=errors)
        value = {'audio': '杨宁/日本語/Français/配音.mp3'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'analysis.json'
            save_json(path, value)
            with patch.object(Path, 'read_text', cp932_read):
                with self.assertRaises(UnicodeDecodeError):
                    path.read_text()
                self.assertEqual(json.loads(path.read_text(encoding='utf8')), value)

    def test_gui_child_uses_utf8(self):
        with patch.object(bootstrap.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            self.assertEqual(bootstrap.invoke(['python', 'app.py']), 0)
            env = run.call_args.kwargs['env']
            self.assertEqual(env['PYTHONUTF8'], '1')
            self.assertEqual(env['PYTHONIOENCODING'], 'utf-8')

if __name__ == '__main__':
    unittest.main()
