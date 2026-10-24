"""Stream-verify Whisper checkpoints without loading the entire archive into RAM.

The stock whisper._download reads the whole ~460MB small checkpoint with f.read()
just to hash it. Some Windows environments fail with OSError(22) at that step.
"""
import hashlib
import os
import re
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def _digest(path, block_size=4 * 1024 * 1024):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(block_size), b''):
            h.update(block)
    return h.hexdigest()


def checkpoint(url, root, in_memory=False):
    parsed = urlparse(url)
    if parsed.scheme != 'https':
        raise ValueError('Whisper模型下载地址必须使用HTTPS。')
    filename = Path(parsed.path).name
    if not filename or not filename.endswith('.pt'):
        raise ValueError('Whisper模型文件名无效。')
    expected = parsed.path.strip('/').split('/')[-2].lower()
    if not re.fullmatch(r'[a-f0-9]{64}', expected):
        raise ValueError('Whisper模型下载地址缺少SHA-256校验值。')
    root = Path(root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    target = root / filename
    if target.is_file():
        if _digest(target) == expected:
            return target.read_bytes() if in_memory else str(target)
        # Keep the user's existing checkpoint for inspection rather than deleting it.
        backup = root / (filename + '.invalid')
        n = 1
        while backup.exists():
            backup = root / (filename + f'.invalid.{n}')
            n += 1
        target.rename(backup)
    fd, temp_name = tempfile.mkstemp(prefix=filename + '.', suffix='.part', dir=str(root))
    try:
        with os.fdopen(fd, 'wb') as dest, urllib.request.urlopen(url, timeout=45) as source:
            while True:
                chunk = source.read(4 * 1024 * 1024)
                if not chunk:
                    break
                dest.write(chunk)
        if _digest(temp_name) != expected:
            raise RuntimeError('模型下载校验失败，请检查网络或代理后重试。')
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return target.read_bytes() if in_memory else str(target)


def load_stable_model(stable_whisper, model_name, cache, device='cpu'):
    """Temporarily replace only Whisper's model download/verify routine."""
    import whisper
    old_download = whisper._download
    whisper._download = checkpoint
    try:
        return stable_whisper.load_model(model_name, device=device, download_root=str(cache))
    finally:
        whisper._download = old_download
