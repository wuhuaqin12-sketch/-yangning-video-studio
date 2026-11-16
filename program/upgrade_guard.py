"""Protect the previous program/configuration before touching a new runtime."""
import json,os,shutil,uuid
from pathlib import Path
from desktop_update import atomic_json

def runtime_dir(root,version):
    from desktop_update import version_tuple
    return Path(root)/'runtimes'/version if version_tuple(version)>=(0,14,0) else Path(root)/'runtime'

def prepare(root,source,settings,version):
    from stable_recovery import preserve_archive,snapshot
    root=Path(root);marker=root/'protected'/('pre-upgrade-'+version+'.json')
    if marker.exists():
        from stable_recovery import verify_archive
        record=json.loads(marker.read_text());verify_archive(record['stable_archive']);return record
    archive=preserve_archive(root,Path(source)/'recovery/v0.12.11-original.zip')
    backup=snapshot(root,settings)
    record=dict(version=version,backup=str(backup),stable_archive=str(archive),runtime=str(runtime_dir(root,version)))
    atomic_json(marker,record)
    return record

def promote_launcher(root,source):
    root=Path(root);temp=root/('desktop_launch.'+uuid.uuid4().hex+'.tmp')
    try:shutil.copyfile(Path(source)/'program/desktop_launch.py',temp);os.replace(temp,root/'desktop_launch.py')
    finally:temp.unlink(missing_ok=True)

def rollback_previous(root,settings):
    """Restore only allowlisted settings from the matching pre-upgrade snapshot."""
    from desktop_update import activate
    from stable_recovery import snapshot,validate_snapshot,SETTINGS
    root=Path(root);settings=Path(settings)
    current=json.loads((root/'current.json').read_text());old=current.get('previous_version')
    if not old:raise ValueError('尚无可恢复的上一版本。')
    marker=root/'protected'/('pre-upgrade-'+current['version']+'.json')
    if not marker.is_file():raise ValueError('未找到对应的升级前配置备份；请使用“恢复到稳定版v12.11”。')
    saved=Path(json.loads(marker.read_text())['backup']);manifest=validate_snapshot(saved)
    pointer=json.loads((saved/'install/current.json').read_text())
    if pointer.get('version')!=old:raise ValueError('备份与上一版本不匹配，未切换程序。')
    if not (root/'versions'/old/'program/app.py').is_file():raise ValueError('上一版本程序不完整，请使用稳定版恢复。')
    values={row['path'].split('/')[-1]:json.loads((saved/row['path']).read_text(encoding='utf8')) for row in manifest['files'] if row['path'].startswith('settings/')}
    before=snapshot(root,settings)
    try:
        for name in SETTINGS:
            if name in values:atomic_json(settings/name,values[name])
            else:(settings/name).unlink(missing_ok=True)
        activate(root,old)
    except Exception:
        for name in SETTINGS:
            path=before/'settings'/name
            if path.is_file():atomic_json(settings/name,json.loads(path.read_text(encoding='utf8')))
            else:(settings/name).unlink(missing_ok=True)
        atomic_json(root/'current.json',current)
        raise
    return old
