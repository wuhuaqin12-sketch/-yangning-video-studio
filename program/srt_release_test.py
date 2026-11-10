"""Exercise the actual previous package's updater against the stable release payload."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from build_cloud_voice_update import payload,descriptor
import legacy_cloud_voice_update_fixture as legacy


class StableBridgeTests(unittest.TestCase):
    def test_original_0_6_updater_accepts_complete_stable_0_7_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(__file__).resolve().parent.parent
            built=payload(root,"b"*40,directory)
            desc=descriptor(built["path"],"c"*40,"正式版0.7.0")
            files=legacy.validate_payload(Path(built["path"]).read_bytes(),desc)
            meta=json.loads(files["preview_version.json"])
            self.assertEqual(meta["release_version"],"0.7.0")
            self.assertEqual(meta["version"],"0.7-preview.1")
            self.assertFalse(meta["formal_studio_release"])
            self.assertIn(b'VERSION = "0.7.0"',files["program/cloud_voice_version.py"])
            self.assertNotIn("program/references/teacher_reference.wav",files)
