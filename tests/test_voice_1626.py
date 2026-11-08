import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "program"))
from voice_1626 import VoiceSettings, LANGUAGES, synthesis_request

class Voice1626Tests(unittest.TestCase):
    def test_five_languages_and_no_style_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "1626.wav"
            ref.write_bytes(b"reference fixture")
            for language in LANGUAGES:
                request = synthesis_request("测试", VoiceSettings(str(ref), language))
                self.assertEqual(request["language"], language)
                self.assertEqual(request["voice_reference_audio"], str(ref.resolve()))
                self.assertNotIn("style_reference_audio", request)
                self.assertNotIn("template_audio", request)

    def test_missing_reference_fails(self):
        with self.assertRaises(ValueError):
            synthesis_request("text", VoiceSettings("missing-1626.wav"))

    def test_empty_text_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "1626.wav"
            ref.touch()
            with self.assertRaises(ValueError):
                synthesis_request(" ", VoiceSettings(str(ref)))

if __name__ == "__main__":
    unittest.main()
