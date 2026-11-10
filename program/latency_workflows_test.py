"""Verify reduced cloud submissions and lossless opening auditions with local fixtures."""
import hashlib
import json
import tempfile
import unittest
import wave
from pathlib import Path

import cloud_voice_core as core
from voxcpm_kaggle_worker import REFERENCE_SHA256
from voice_workflows import export_opening_preview


class LatencyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.jobs = self.root / "jobs"
        self.text = "The first complete sentence. " + "A later complete sentence. " * 20

    def job(self, **options):
        args = dict(root=self.jobs, username="member", dataset="owner/private", text=self.text,
                    language="英语", seed=42, output_dir=self.root / "output", include_preview=True,
                    reuse_completed=True)
        args.update(options)
        return core.prepare_job(**args)

    def complete(self):
        path = self.job()
        manifest = json.loads(path.read_text())
        request = json.loads((path.parent / "request.json").read_text())
        folder = path.parent / "download"
        folder.mkdir()
        # Includes exact internal silent samples; preview must preserve every one.
        data = (b"\x01\x00" * 24000 + b"\x00\x00" * 24000 + b"\x02\x00" * 96000)
        for name in ("yangning_final.wav", "yangning_raw.wav"):
            with wave.open(str(folder / name), "wb") as output:
                output.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
                output.writeframes(data)
        (folder / "script.txt").write_text(self.text)
        recipe = dict(job_id=manifest["job_id"], status="generated_pending_review", language="英语",
                      reference_sha256=REFERENCE_SHA256, template_audio_used=False, silence_trimmed=False,
                      pitch_ratio=1.0, profile={"tempo":1.0}, postprocess=request["postprocess"])
        core.save_json(folder / "voice_recipe.json", recipe)
        core.save_json(folder / "segments.json", dict(audio_sha256=hashlib.sha256((folder / "yangning_final.wav").read_bytes()).hexdigest(),
                timing="generated_units", segments=[dict(start=0, end=1.5, text=request["units"][0]["text"]), dict(start=1.5,end=3,text="Remaining text.")]))
        manifest["artifacts"] = core.deliver_result(path.parent, manifest)
        manifest.update(status="completed", cleanup_status="deleted", result_hashes=core.result_hashes(manifest["artifacts"]))
        core.save_json(path, manifest)
        return path, manifest, data

    def test_full_and_preview_use_one_script_and_opening_samples_are_unchanged(self):
        path, manifest, data = self.complete()
        request = json.loads((path.parent / "request.json").read_text())
        self.assertEqual("".join(self.text.split()), "".join(" ".join(unit["text"] for unit in request["units"]).split()))
        self.assertLess(len(request["units"][0]["text"]), len(self.text))
        self.assertTrue(request["units"][0]["text"].endswith("."))
        with wave.open(manifest["artifacts"]["preview_audio"], "rb") as preview:
            self.assertEqual(preview.readframes(preview.getnframes()), data)
        with wave.open(manifest["artifacts"]["yangning_final.wav"], "rb") as whole:
            self.assertEqual(whole.readframes(whole.getnframes()), data)

    def test_identical_request_reuses_without_credentials_or_any_cloud_call(self):
        original, old, _ = self.complete()
        path = self.job()
        self.assertEqual(json.loads(path.read_text())["reuse_from"], str(original))
        events = []
        def forbidden(*args, **kwargs):
            self.fail("An exact local cache hit must not submit or download a cloud job")
        result = core.run_job(path, "", events.append, cli=forbidden)
        state = json.loads(path.read_text())
        self.assertEqual(state["cleanup_status"], "not_submitted")
        self.assertFalse(state["cloud_submitted"])
        self.assertNotEqual(result["yangning_final.wav"], old["artifacts"]["yangning_final.wav"])
        self.assertEqual(Path(result["yangning_final.wav"]).read_bytes(), Path(old["artifacts"]["yangning_final.wav"]).read_bytes())
        core.run_job(path, "", events.append, cli=forbidden)  # Recovery also remains offline.

    def test_changed_settings_or_damaged_audio_do_not_reuse(self):
        _, old, _ = self.complete()
        for options in ({"seed":43}, {"tempo":.9}, {"text":self.text + "Changed."}, {"light_denoise":False}, {"gain_db":2}, {"reuse_completed":False}, {"language":"德语"}, {"username":"another"}):
            self.assertNotIn("reuse_from", json.loads(self.job(**options).read_text()), options)
        Path(old["artifacts"]["yangning_final.wav"]).write_bytes(b"damaged")
        self.assertNotIn("reuse_from", json.loads(self.job().read_text()))

    def test_damaged_cached_copy_is_rejected_on_recovery_without_submission(self):
        self.complete()
        path = self.job()
        result = core.run_job(path, "", lambda _: None, cli=lambda *a, **k:self.fail("cloud call"))
        Path(result["yangning_final.wav"]).unlink()
        with self.assertRaisesRegex(ValueError, "已移动或改变"):
            core.run_job(path, "", lambda _:None, cli=lambda *a, **k:self.fail("cloud call"))
