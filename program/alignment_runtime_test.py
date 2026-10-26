import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import alignment_runtime as ar
import multilingual as m

class RuntimeTests(unittest.TestCase):
    def test_dll_and_memory_messages_are_distinct(self):
        self.assertIn('运行组件',m.failure_message('OSError [WinError 1114] c10.dll'))
        self.assertIn('内存',m.failure_message('DefaultCPUAllocator: not enough memory'))
        self.assertNotIn('首次',m.failure_message('HTTP download failed'))
    def test_small_is_used_and_failures_do_not_downgrade(self):
        model=object()
        with patch('model_cache.load_stable_model',return_value=model) as load:
            self.assertEqual(m.load_with_fallback(None,Path('.'),lambda s:None),(model,'small'))
            self.assertEqual(load.call_args.args[1],'small')
        for error in [RuntimeError('not enough memory'),OSError('network offline')]:
            with patch('model_cache.load_stable_model',side_effect=error) as load:
                with self.assertRaises(type(error)):
                    m.load_with_fallback(None,Path('.'),lambda s:None)
                self.assertEqual(load.call_count,1)
    def test_healthy_environment_is_reused(self):
        with patch.object(ar,'healthy',return_value=True),patch.object(ar.subprocess,'run') as run:
            self.assertEqual(ar.prepare(lambda s:None),ar.python_path(ar.runtime_path()))
            run.assert_not_called()
    def test_failed_environment_preserved_cpu_install_and_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'runtime';root.mkdir();(root/'old.txt').write_text('keep')
            def create(path):path.mkdir()
            with patch.object(ar,'runtime_path',return_value=root),patch.object(ar,'healthy',side_effect=[False,True]),patch.object(ar.venv.EnvBuilder,'create',side_effect=create),patch.object(ar.subprocess,'run') as run:
                ar.prepare(lambda s:None)
                self.assertTrue(next(Path(tmp).glob('runtime.backup_*')).joinpath('old.txt').exists())
                self.assertIn('https://download.pytorch.org/whl/cpu',run.call_args_list[0].args[0])
                self.assertIn('torch==2.6.0',run.call_args_list[0].args[0])
                self.assertIn('-c',run.call_args_list[1].args[0])

if __name__=='__main__':unittest.main()
