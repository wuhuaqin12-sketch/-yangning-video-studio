"""Whole-track A/B audio previews; separate names from 60-second spot checks."""
import json,hashlib
from pathlib import Path
from media import run,executable

def preview_full(folder,cancel,original=False):
    folder=Path(folder).resolve();args=[executable('ffmpeg'),'-v','error','-y']
    if (folder/'clean_project.json').is_file():
        from clean_project import load,rebuild
        load(folder)
        if not original:rebuild(folder,cancel)
        source=folder/('original.wav' if original else 'edited.wav')
    else:
        m=json.loads((folder/'analysis.json').read_text(encoding='utf8'))
        from voice_clean import enabled
        source=folder/('original.f32' if original or not enabled(m['job']) else 'enhanced.f32')
        args+=['-f','f32le','-ar',str(m['rate']),'-ac',str(m['channels'])]
    if not source.is_file():raise ValueError('请先完成声音处理，再生成整段试听。')
    info=source.stat()
    token=hashlib.sha256(json.dumps([str(source),info.st_size,info.st_mtime_ns,args]).encode()).hexdigest()[:12]
    target=folder/(('整段_原声_' if original else '整段_处理后_')+token+'.m4a')
    if target.is_file():return str(target)
    partial=target.with_name(target.stem+'.partial.m4a')
    try:
        run(args+['-i',str(source),'-map','0:a:0','-c:a','aac','-b:a','192k',str(partial)],cancel)
        partial.replace(target)
        return str(target)
    finally:partial.unlink(missing_ok=True)
