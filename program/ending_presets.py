"""Private language-specific ending copies, independent of video cut positions."""
import hashlib,json,re,shutil,uuid,threading
from pathlib import Path
from desktop_update import atomic_json

def language_key(language):
    code=str(language).strip().lower()
    if code in ('','other','auto') or not re.fullmatch(r'[a-z]{2,8}(?:-[a-z0-9]{2,8})*',code):raise ValueError('请先明确选择片尾语言。')
    return code

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()

def save_preset(root,language,source):
    code=language_key(language);source=Path(source)
    if not source.is_file():raise ValueError('请先选择已制作好的对应语言片尾视频。')
    from media import probe
    if not any(s.get('codec_type')=='video' for s in probe(str(source),threading.Event()).get('streams',[])):raise ValueError('片尾文件必须包含视频画面。')
    directory=Path(root)/code;directory.mkdir(parents=True,exist_ok=True)
    fingerprint=digest(source);target=directory/(fingerprint+source.suffix.lower())
    if not target.is_file() or digest(target)!=fingerprint:
        temporary=directory/(uuid.uuid4().hex+'.tmp')
        try:
            shutil.copyfile(source,temporary)
            if digest(temporary)!=fingerprint:raise ValueError('复制期间原片尾发生变化，请重试。')
            temporary.replace(target)
        finally:temporary.unlink(missing_ok=True)
    atomic_json(directory/'preset.json',dict(schema=1,language=code,file=target.name,sha256=fingerprint))
    return target

def load_preset(root,language):
    code=language_key(language);directory=Path(root)/code;index=directory/'preset.json'
    if not index.is_file():return None
    data=json.loads(index.read_text(encoding='utf-8-sig'))
    if data.get('schema')!=1 or data.get('language')!=code:raise ValueError('片尾预设格式或语言不匹配。')
    filename=data.get('file','')
    if not isinstance(filename,str) or not filename or Path(filename).name!=filename or '/' in filename or '\\' in filename:raise ValueError('片尾预设路径无效。')
    target=directory/filename
    if not target.is_file():raise ValueError('保存的片尾副本已丢失，请重新保存。')
    if digest(target)!=data.get('sha256'):raise ValueError('保存的片尾副本发生变化，请重新确认。')
    return target
