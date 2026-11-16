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
