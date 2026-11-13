"""Build complete CloudVoice updates from the updater's allowed-file inventory."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent / 'cloudvoice_candidate'
sys.path.insert(0, str(ROOT / 'program'))
import cloud_voice_update as updater

def build(revision):
    version = json.loads((ROOT / 'preview_version.json').read_text(encoding='utf-8'))
    version['source_revision'] = revision
    files = {}
    for path in sorted(ROOT.rglob('*')):
        name = path.relative_to(ROOT).as_posix()
        if not path.is_file() or not updater.allowed_file(name):
            continue
        data = path.read_bytes()
        if name == 'preview_version.json':
            data = (json.dumps(version, ensure_ascii=False, indent=2) + '\n').encode()
        files[name] = dict(content=base64.b64encode(data).decode(), sha256=hashlib.sha256(data).hexdigest())
    assert updater.REQUIRED.issubset(files)
    assert 'program/punctuation_pause.py' in files
    return dict(product=updater.PRODUCT, sequence=version['update_sequence'],
                version=version['version'], source_revision=revision, files=files)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('revision')
    parser.add_argument('output')
    args = parser.parse_args()
    Path(args.output).write_text(json.dumps(build(args.revision), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
