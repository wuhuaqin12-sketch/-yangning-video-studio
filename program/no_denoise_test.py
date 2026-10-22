"""Verify original PCM survives old enabled flags, with no noise-processing runtime."""
import unittest,json
from pathlib import Path
from scipy.io import wavfile
import numpy as np
import clean_project as cp
import clean_project_test as fixtures
from workflow import normalize

class OriginalSoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):fixtures.CleanTests.setUpClass()
    @classmethod
    def tearDownClass(cls):fixtures.CleanTests.tearDownClass()
    def test_old_enabled_flags_cannot_filter_pcm(self):
        f=Path(cp.prepare(dict(video=str(fixtures.CleanTests.video),source_srt=str(fixtures.CleanTests.srt),output=str(fixtures.CleanTests.root),auto_cut=False,denoise=True,separate=True,mute=True,clean_mode='strong'),fixtures.CleanTests.cancel))
        _,a=wavfile.read(f/'original.wav');_,b=wavfile.read(f/'enhanced.wav');_,c=wavfile.read(f/'edited.wav')
        np.testing.assert_array_equal(a,b);np.testing.assert_array_equal(a,c)
        self.assertIsNone(cp.load(f)['separation']);self.assertFalse(cp.load(f)['denoise']['enabled'])
        self.assertFalse((f/'video.mp4').exists());self.assertTrue((f/'preview.mp4').exists())
        m=cp.load(f);m['version']='0.9.0';cp.save(f/'clean_project.json',m)
        with self.assertRaisesRegex(ValueError,'旧工程'):cp.load(f)
    def test_direct_export_skips_previews(self):
        f=Path(cp.prepare(dict(video=str(fixtures.CleanTests.video),source_srt=str(fixtures.CleanTests.srt),output=str(fixtures.CleanTests.root),auto_cut=False),fixtures.CleanTests.cancel,make_previews=False))
        self.assertFalse((f/'preview.mp4').exists());self.assertFalse((f/'试听_处理后.m4a').exists())
        result=cp.export(f,fixtures.CleanTests.cancel)
        self.assertTrue(Path(result).exists());self.assertFalse((f/'preview.mp4').exists())
    def test_legacy_normalization_disables_removed_flags(self):
        f=fixtures.CleanTests
        j=normalize(dict(video=str(f.video),audio=str(f.video),source_srt=str(f.srt),target_srt=str(f.srt),output=str(f.root),alignment='timed',denoise=True,separate=True,mute=True))
        self.assertFalse(j['denoise']);self.assertFalse(j['separate']);self.assertFalse(j['mute'])

if __name__=='__main__':unittest.main(verbosity=2)
