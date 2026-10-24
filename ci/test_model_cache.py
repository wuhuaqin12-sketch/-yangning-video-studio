import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'program'))
import model_cache

class ModelCacheTests(unittest.TestCase):
    def test_existing_cache_is_verified_in_chunks(self):
        data=b'valid-checkpoint-data'
        sha=hashlib.sha256(data).hexdigest()
        url=f'https://example.org/models/{sha}/small.pt'
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'small.pt').write_bytes(data)
            with patch.object(model_cache.urllib.request,'urlopen',side_effect=AssertionError('download not needed')):
                self.assertEqual(model_cache.checkpoint(url,folder),str(Path(folder)/'small.pt'))
    def test_corrupt_cache_preserved_and_replaced(self):
        data=b'new-valid-data'
        sha=hashlib.sha256(data).hexdigest()
        url=f'https://example.org/models/{sha}/small.pt'
        from io import BytesIO
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'small.pt').write_bytes(b'old-broken')
            with patch.object(model_cache.urllib.request,'urlopen',return_value=BytesIO(data)):
                result=model_cache.checkpoint(url,folder)
            self.assertEqual(Path(result).read_bytes(),data)
            self.assertEqual((Path(folder)/'small.pt.invalid').read_bytes(),b'old-broken')
    def test_bad_download_keeps_old_copy(self):
        data=b'correct'
        sha=hashlib.sha256(data).hexdigest()
        url=f'https://example.org/models/{sha}/small.pt'
        from io import BytesIO
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'small.pt').write_bytes(b'old')
            with patch.object(model_cache.urllib.request,'urlopen',return_value=BytesIO(b'incorrect')):
                with self.assertRaisesRegex(RuntimeError,'校验失败'):
                    model_cache.checkpoint(url,folder)
            self.assertEqual((Path(folder)/'small.pt.invalid').read_bytes(),b'old')
            self.assertFalse((Path(folder)/'small.pt').exists())
    def test_insecure_url_rejected(self):
        with self.assertRaises(ValueError):
            model_cache.checkpoint('http://example.org/small.pt','/tmp')

if __name__=='__main__':unittest.main()
