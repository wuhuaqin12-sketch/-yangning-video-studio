"""Remember and honor the chosen final movie destination."""
import json
import os
import shutil
from pathlib import Path

PREFS = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'YangNingStudio' / 'output_destination.json'

def remember(path):
    target = Path(str(path).strip()).expanduser()
    if not str(path).strip():
        raise ValueError('请选择成片保存文件夹。')
    target.mkdir(parents=True, exist_ok=True)
    if not target.is_dir():
        raise ValueError('保存位置不是文件夹。')
    PREFS.parent.mkdir(parents=True, exist_ok=True)
    temp = PREFS.with_suffix('.tmp')
    temp.write_text(json.dumps({'output': str(target.resolve())}, ensure_ascii=False), encoding='utf-8')
    temp.replace(PREFS)
    return str(target.resolve())

def preferred(fallback):
    try:
        value = json.loads(PREFS.read_text(encoding='utf-8')).get('output')
        return value if isinstance(value, str) and value.strip() else fallback
    except (OSError, ValueError, TypeError):
        return fallback

def deliver(movie, destination):
    source = Path(movie).resolve(strict=True)
    target_dir = Path(destination).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    if source.parent == target_dir:
        return str(source)
    target = target_dir / source.name
    if target.exists():
        stem, suffix = source.stem, source.suffix
        index = 1
        while target.exists():
            target = target_dir / f'{stem}_{index}{suffix}'
            index += 1
    temp = target.with_name(target.name + '.partial')
    try:
        shutil.copy2(source, temp)
        temp.replace(target)
    finally:
        if temp.exists():
            temp.unlink()
    return str(target)
