"""Install once without admin privileges. User projects remain outside app versions."""
import json,os,shutil,subprocess,sys,tempfile,zipfile
from pathlib import Path
from desktop_update import APP_VERSION,install_root,stage_package,activate,version_tuple,save_config

def install():
    if os.name!='nt':raise RuntimeError('此安装器用于 Windows 10 / 11。')
    root=install_root();source=Path(__file__).resolve().parent.parent
    root.mkdir(parents=True,exist_ok=True)
    if (root/'current.json').exists():
        current=json.loads((root/'current.json').read_text())['version']
        if version_tuple(current)>version_tuple(APP_VERSION):
            raise ValueError('已安装的版本更新，请从桌面直接打开。')
    with tempfile.TemporaryDirectory() as d:
        archive=Path(d)/'app.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for p in source.rglob('*'):
                if p.is_file() and not any(part in ('.venv','__pycache__','.git') or part.startswith('.venv.failed_') for part in p.parts):
                    z.write(p,p.relative_to(source))
        target=root/'versions'/APP_VERSION
        if not target.exists():stage_package(archive,root,APP_VERSION)
    env=os.environ.copy();env['YANGNING_INSTALL_ROOT']=str(root);env['PYTHONUTF8']='1'
    subprocess.run([sys.executable,str(target/'program'/'bootstrap.py'),'--setup-only'],env=env,check=True)
    # Keep this stable launcher backward compatible across app updates.
    shutil.copyfile(target/'program'/'desktop_launch.py',root/'desktop_launch.py')
    from windows_shortcut import create_shortcuts
    create_shortcuts(root/'runtime'/'Scripts'/'pythonw.exe',root/'desktop_launch.py',root)
    activate(root,APP_VERSION)
    release=json.loads((source/'release.json').read_text())
    if release.get('update_manifest_url') and not (root/'update_config.json').exists():
        save_config(release['update_manifest_url'],root)
    print('安装完成：以后请双击桌面的“杨宁视频工作室”。')
    if '--quiet' in sys.argv:return
    import ctypes
    ctypes.windll.user32.MessageBoxW(None,'安装完成。以后请双击桌面上的“杨宁视频工作室”。\n已内置更新地址，发布新版后会提示更新。','安装完成',64)

if __name__=='__main__':
    try:install()
    except Exception as e:
        print('安装失败：',e)
        if '--quiet' not in sys.argv:input('请保留错误信息，按回车关闭。')
        sys.exit(1)
