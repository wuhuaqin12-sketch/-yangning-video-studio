import subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
import bootstrap
from python_check import rejection_reason,store_path

class BootstrapTests(unittest.TestCase):
    def test_store_alias_and_hidden_base_are_rejected(self):
        self.assertTrue(store_path(r'C:\Users\u\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.12_abcd\python.exe'))
        self.assertTrue(rejection_reason((3,12),64,[r'C:\normal\runtime\Scripts\python.exe',r'C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.12_abcd\python.exe']))
        self.assertFalse(store_path(r'C:\Users\WindowsAppsUser\Programs\Python312\python.exe'))
        self.assertEqual(rejection_reason((3,12),64,[r'C:\Users\u\AppData\Local\Programs\Python\Python312\python.exe']),'')
        self.assertTrue(rejection_reason((3,12),32,[]));self.assertTrue(rejection_reason((3,9),64,[]))
    def test_missing_config_never_counts_as_installed(self):
        with tempfile.TemporaryDirectory() as d:
            env=Path(d)/'runtime';py=env/'Scripts/python.exe';py.parent.mkdir(parents=True);py.write_bytes(b'old broken exe')
            with patch.object(bootstrap,'ENV',env),patch.object(bootstrap,'PY',py),patch.object(bootstrap.subprocess,'run') as run:
                self.assertFalse(bootstrap.runtime_health());run.assert_not_called()
            (env/'pyvenv.cfg').write_text('home=missing')
            with patch.object(bootstrap,'ENV',env),patch.object(bootstrap,'PY',py),patch.object(bootstrap.subprocess,'run',return_value=subprocess.CompletedProcess([],1)):
                self.assertFalse(bootstrap.runtime_health())
    def test_broken_runtime_is_preserved_and_rebuilt_without_touching_projects(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);env=root/'runtime';env.mkdir();(env/'old.txt').write_text('failed attempt')
            project=root/'Videos'/'video.mp4';project.parent.mkdir();project.write_bytes(b'preserve original video')
            def create(target):
                target.mkdir();(target/'pyvenv.cfg').write_text('new config')
            builder=MagicMock();builder.create.side_effect=create
            with patch.object(bootstrap,'ENV',env),patch.object(bootstrap,'PY',env/'Scripts/python.exe'),patch.object(bootstrap,'runtime_health',side_effect=[False,True]),patch.object(bootstrap.venv,'EnvBuilder',return_value=builder):
                bootstrap.ensure_runtime()
            saved=list(root.glob('runtime.failed_*'));self.assertEqual(len(saved),1)
            self.assertEqual((saved[0]/'old.txt').read_text(),'failed attempt')
            self.assertTrue((env/'pyvenv.cfg').exists());self.assertEqual(project.read_bytes(),b'preserve original video')
    def test_healthy_runtime_is_not_reinstalled(self):
        with patch.object(bootstrap,'runtime_health',return_value=True),patch.object(bootstrap.venv,'EnvBuilder') as builder:
            bootstrap.ensure_runtime();builder.assert_not_called()
    def test_failed_rebuild_never_reports_success(self):
        with tempfile.TemporaryDirectory() as d:
            env=Path(d)/'runtime'
            builder=MagicMock();builder.create.side_effect=lambda p:p.mkdir()
            with patch.object(bootstrap,'ENV',env),patch.object(bootstrap,'runtime_health',return_value=False),patch.object(bootstrap.venv,'EnvBuilder',return_value=builder):
                with self.assertRaisesRegex(RuntimeError,'新运行环境检查失败'):bootstrap.ensure_runtime()
    def test_live_runtime_is_not_renamed(self):
        with tempfile.TemporaryDirectory() as d:
            env=Path(d)/'runtime';env.mkdir();py=env/'Scripts/python.exe'
            with patch.object(bootstrap,'ENV',env),patch.object(bootstrap,'PY',py),patch.object(bootstrap,'runtime_health',return_value=False),patch.object(sys,'executable',str(py)):
                with self.assertRaisesRegex(RuntimeError,'运行环境需要修复'):bootstrap.ensure_runtime()
            self.assertTrue(env.exists());self.assertFalse(list(Path(d).glob('runtime.failed_*')))

if __name__=='__main__':unittest.main()
