"""Pinned stable-package protection. Never mutates project/media/output directories.

Archive verification is distinct from a Windows runtime/GUI smoke test. Activation
requires a successful caller-supplied health check and preserves all newer files.
"""
import hashlib,json,os,shutil,tempfile,uuid,zipfile
from datetime import datetime,timezone
from pathlib import Path
from desktop_update import atomic_json,stage_package,activate,fetch

STABLE_VERSION='0.12.11'
STABLE_SIZE=25417118
STABLE_SHA256='ac6b5a09c35d92c88c986334b959c4847540a0175b05d9cc0321235be60f200e'
STABLE_URL='https://github.com/wuhuaqin12-sketch/-yangning-video-studio/releases/download/v0.12.11/YangNing_VideoStudio_Windows_0.12.11.zip'
SETTINGS=('queue_noerase_v055.json','style_no_denoise.json','sound_preferences.json','output_destination.json')

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def verify_archive(path):
    path=Path(path)
    if not path.is_file() or path.stat().st_size!=STABLE_SIZE or digest(path)!=STABLE_SHA256:
        raise ValueError('v12.11原始恢复包大小或SHA-256不符，未改变现有版本。')
    with zipfile.ZipFile(path) as z:
        if z.testzip():raise ValueError('v12.11压缩包损坏。')
        release=json.loads(z.read('release.json'))
        if release.get('version')!=STABLE_VERSION or release.get('app')!='YangNingStudio':
            raise ValueError('恢复包版本不符。')
        required=['program/'+n for n in ('app.py','bootstrap.py','desktop_update.py','desktop_launch.py','requirements.txt')]
        if any(n not in z.namelist() for n in required):raise ValueError('恢复包缺少程序文件。')
        return dict(version=STABLE_VERSION,sha256=STABLE_SHA256,size=STABLE_SIZE,
                    archive_verified=True,windows_launch_verified=False,
                    bundled_ffmpeg=all('program/tools/'+n+'.exe' in z.namelist() for n in ('ffmpeg','ffprobe')))

def preserve_archive(root,source=None,cancel=None):
    root=Path(root);dest=root/'protected'/'v0.12.11-original.zip'
    if dest.exists():verify_archive(dest);return dest
    dest.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.stable-',suffix='.zip',dir=dest.parent);os.close(fd)
    temp=Path(name)
    try:
        if source is None:fetch(STABLE_URL,STABLE_SIZE,temp,cancel)
        else:shutil.copyfile(source,temp)
        report=verify_archive(temp)
        os.replace(temp,dest)
        atomic_json(dest.with_suffix('.json'),report)
    finally:temp.unlink(missing_ok=True)
    return dest

def snapshot(root,settings_root):
    root=Path(root);settings_root=Path(settings_root)
    dest=root/'backups'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    dest.mkdir(parents=True)
    manifest={'schema':1,'created_at':datetime.now(timezone.utc).isoformat(),'files':[],
              'scope':'app settings and version pointer only; no media or exports'}
    for base,names,prefix in [(root,('current.json','update_config.json'),'install'),(settings_root,SETTINGS,'settings')]:
        for name in names:
            p=base/name
            if not p.is_file():continue
            if p.is_symlink():raise ValueError('配置文件是符号链接，停止备份：'+name)
            target=dest/prefix/name;target.parent.mkdir(exist_ok=True)
            shutil.copyfile(p,target)
            manifest['files'].append({'path':prefix+'/'+name,'sha256':digest(target)})
    atomic_json(dest/'manifest.json',manifest)
    return dest

def validate_snapshot(path):
    path=Path(path);m=json.loads((path/'manifest.json').read_text(encoding='utf8'))
    allowed={'settings/'+n for n in SETTINGS}|{'install/current.json','install/update_config.json'}
    if m.get('schema')!=1:raise ValueError('备份格式无效。')
    for row in m['files']:
        if row['path'] not in allowed or digest(path/row['path'])!=row['sha256']:
            raise ValueError('备份文件校验失败。')
    return m

def stage_stable(root,archive):
    root=Path(root);verify_archive(archive)
    target=root/'versions'/STABLE_VERSION
    if not target.exists():return stage_package(archive,root,STABLE_VERSION)[1]
    # Do not silently replace an installed or modified stable copy.
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if info.is_dir():continue
            local=target/info.filename
            if local.is_symlink() or not local.is_file() or digest(local)!=hashlib.sha256(z.read(info)).hexdigest():
                raise ValueError('已安装的v12.11与原包不一致；保留现场，未切换版本。')
    return target

def restore(root,settings_root,archive,healthcheck,stable_settings=None):
    """healthcheck(target) must run setup + executable/import/GUI checks on Windows.

    A failed check changes neither the active pointer nor the active settings.
    Newer settings and media are never removed. Stable settings must come from
    an explicitly selected pre-upgrade snapshot, not the newest backup.
    """
    root=Path(root);settings_root=Path(settings_root)
    protected=preserve_archive(root,archive)
    before=snapshot(root,settings_root)
    target=stage_stable(root,protected)
    evidence=healthcheck(target)
    if not isinstance(evidence,dict) or evidence.get('platform')!='win32' or evidence.get('passed') is not True:
        raise RuntimeError('尚未通过Windows运行环境与启动检查；未启用v12.11。')
    if stable_settings:
        stable_settings=Path(stable_settings);m=validate_snapshot(stable_settings)
        pointer=stable_settings/'install/current.json'
        if not pointer.is_file() or json.loads(pointer.read_text())['version']!=STABLE_VERSION:
            raise ValueError('所选备份不是v12.11配置快照。')
        # Validate JSON before touching any live file.
        values={row['path'].split('/')[-1]:json.loads((stable_settings/row['path']).read_text(encoding='utf8'))
                for row in m['files'] if row['path'].startswith('settings/')}
        try:
            for name,value in values.items():atomic_json(settings_root/name,value)
            activate(root,STABLE_VERSION)
        except Exception:
            # Roll back written configuration; never delete a source or output.
            for name in values:
                saved=before/'settings'/name
                if saved.exists():atomic_json(settings_root/name,json.loads(saved.read_text(encoding='utf8')))
                else:(settings_root/name).unlink(missing_ok=True)
            raise
    else:
        # Default recovery uses a dedicated clean profile via the recovery launcher.
        # Do not mark the normal shared-profile launcher safe without old settings.
        raise RuntimeError('原始恢复包已保护、程序已检查；还需v12.11配置快照，或先验证独立干净配置的恢复启动器。未切换版本。')
    atomic_json(root/'protected'/'last_restore.json',{'version':STABLE_VERSION,'backup':str(before),'healthcheck':evidence})
    return target
