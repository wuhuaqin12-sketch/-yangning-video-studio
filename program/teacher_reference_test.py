"""Reference transport regression tests; synthetic fixtures never use private voice bytes."""
import base64
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import cloud_voice_core as core
import voxcpm_kaggle_worker as worker


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data = b"synthetic-approved-reference-fixture"
        self.sha = hashlib.sha256(self.data).hexdigest()
        for module in (core, worker):
            guard = patch.object(module, "REFERENCE_SHA256", self.sha)
            guard.start()
            self.addCleanup(guard.stop)

    def test_missing_mount_uses_verified_private_fallback_and_rejects_other_voice(self):
        request = {"reference_path": str(self.root / "missing.wav")}
        encoded = base64.b64encode(self.data).decode()
        result = worker.resolve_teacher_reference(request, self.root / "absent", encoded, self.root)
        self.assertEqual(result.read_bytes(), self.data)
        with self.assertRaises(ValueError):
            worker.resolve_teacher_reference(request, self.root / "absent", base64.b64encode(b"wrong").decode(), self.root)

    def test_nested_duplicate_extension_and_any_rename_match_content(self):
        mounted = self.root / "mount" / "nested"
        mounted.mkdir(parents=True)
        for name in ("1626_reference.wav.wav", "老师原声.wav"):
            reference = mounted / name
            reference.write_bytes(self.data)
            request = {"reference_path": str(self.root / "missing.wav")}
            self.assertEqual(worker.resolve_teacher_reference(request, mounted, "invalid-fallback"), reference)
            reference.unlink()

    def test_dataset_download_verifies_and_reuses_cache(self):
        job = self.root / "jobs" / "job1"
        job.mkdir(parents=True)
        calls = []
        def cli(args, env, timeout):
            calls.append(args)
            target = Path(args[args.index("-p") + 1]) / "data.zip"
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("nested/1626_reference.wav.wav", self.data)
        self.assertEqual(core.ensure_teacher_reference(job, "owner/private", {}, cli, lambda _: None), self.data)
        self.assertEqual(core.ensure_teacher_reference(job, "owner/private", {}, cli, lambda _: None), self.data)
        self.assertEqual(len(calls), 1)

    def test_wrong_reference_prevents_cloud_submission(self):
        manifest = core.prepare_job(self.root / "jobs", "member", "owner/private", "试听。", "粤语", 1, self.root / "output")
        calls = []
        def cli(args, env, timeout):
            calls.append(args[:2])
            if args[:2] == ["datasets", "download"]:
                target = Path(args[args.index("-p") + 1]) / "wrong.wav"
                target.write_bytes(b"another voice")
        with self.assertRaisesRegex(RuntimeError, "尚未提交"):
            core.run_job(manifest, "temporary-test-secret", lambda _: None, cli=cli)
        self.assertEqual(calls, [["datasets", "download"]])
        self.assertEqual(json.loads(manifest.read_text())["status"], "prepared")

    def test_private_notebook_embeds_only_approved_reference_separate_from_request(self):
        request = {"job_id": "test", "text": "原稿"}
        notebook = core.build_notebook(request, self.data)
        scope = {}
        exec("".join(notebook["cells"][2]["source"]), scope)
        self.assertEqual(scope["REQUEST"], request)
        self.assertEqual(base64.b64decode(scope["TEACHER_REFERENCE_B64"]), self.data)
        with self.assertRaises(ValueError):
            core.build_notebook(request, b"template-voice")
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                compile("".join(cell["source"]), "notebook", "exec")
