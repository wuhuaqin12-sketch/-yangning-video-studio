"""Build an allowlisted standalone preview, excluding model/user data and secrets."""
import argparse
import ast
import hashlib
import json
import zipfile
from pathlib import Path

FILES = (
    "START_CLOUD_VOICE_PREVIEW.bat", "launch_cloud_voice_preview.ps1", "preview_requirements.txt",
    "README_CLOUD_PREVIEW.zh-CN.md", "KAGGLE_VOXCPM2_SETUP.md", "CLOUD_VOICE_EDITING_REQUIREMENTS.md",
    "program/cloud_voice_preview.py", "program/preview_python_check.py", "program/cloud_voice_core.py", "program/kaggle_voice.py",
    "program/voxcpm_kaggle_worker.py", "program/voice_clip_edit.py", "program/cloud_voice_test.py",
)


def build(root, output, revision):
    root, output = Path(root), Path(output)
    payloads = {}
    prefix = "YangNing_CloudVoice_Independent_Preview"
    for name in FILES:
        source = root / name
        data = source.read_bytes()
        if source.suffix == ".py":
            ast.parse(data.decode("utf-8"), filename=name)
        if source.suffix in (".bat", ".ps1"):
            data = data.decode("utf-8").replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
        payloads[name] = data
    payloads["preview_version.json"] = json.dumps({
        "name": "YangNing Cloud Voice Independent Preview", "version": "0.1-preview.1",
        "source_revision": revision, "formal_studio_release": False,
        "local_validation": "22 tests passed; real FFmpeg exports exercised",
        "pending_validation": ["Windows GUI", "PowerShell setup", "Kaggle account authorization", "real GPU inference", "teacher-voice and join listening"],
        "reference_audio_bundled": False,
    }, ensure_ascii=False, indent=2).encode("utf-8")
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
    payloads["FILES_SHA256.json"] = json.dumps(manifest, indent=2).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads.items():
            archive.writestr(prefix + "/" + name, data)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
        for name, digest in manifest.items():
            if hashlib.sha256(archive.read(prefix + "/" + name)).hexdigest() != digest:
                raise ValueError("Packaged file checksum mismatch: " + name)
    return {"path": str(output.resolve()), "files": len(payloads), "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    print(json.dumps(build(Path(__file__).parent, args.output, args.revision)))
