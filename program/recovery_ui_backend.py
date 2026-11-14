"""Recover the original stable program using an independent runtime and profile."""
import json,os,sys,shutil
from pathlib import Path
from desktop_update import install_root,atomic_json
from stable_recovery import preserve_archive,stage_stable,snapshot,STABLE_VERSION
from media import run

def restore_isolated(cancel,progress=lambda s:None):
    if os.name!='nt':raise RuntimeError('稳定版恢复启动需要Windows；本环境不会伪报启动成功。')
    root=install_root()
    if not (root/'preview_profile.json').exists():
        root=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'YangNingStudioDesktopPreview'
        atomic_json(root/'preview_profile.json',{'channel':'test','isolated_profile':True})
    profile=root/'profile/YangNingStudio'
    snapshot(root,profile)
    progress('校验并保护原始v12.11恢复包…')
    bundled=Path(__file__).parent.parent/'recovery/v0.12.11-original.zip'
    archive=preserve_archive(root,bundled if bundled.is_file() else None,cancel=cancel);target=stage_stable(root,archive)
    isolated=root/'stable-v12.11';isolated.mkdir(exist_ok=True)
    env={'YANGNING_INSTALL_ROOT':str(isolated),'LOCALAPPDATA':str(isolated/'profile')}
    python=isolated/'runtime/Scripts/python.exe'
    progress('在独立运行环境准备v12.11，不修改新版或原稳定版依赖…')
    script=isolated/'prepare_stable.py'
    script.write_text('import os,subprocess,sys\nos.environ.update('+repr(env)+')\nos.environ.pop("YANGNING_DATA_ROOT",None)\nsubprocess.run([sys.executable,'+repr(str(target/'program/bootstrap.py'))+',"--setup-only"],check=True)\n',encoding='utf8')
    run([sys.executable,str(script)],cancel)
    check=isolated/'check_stable.py'
    check.write_text('import sys,subprocess,tkinter as tk\nsys.path.insert(0,'+repr(str(target/'program'))+')\nfrom media import executable\nfor name in ("ffmpeg","ffprobe"):subprocess.run([executable(name),"-version"],check=True,capture_output=True)\nfrom app import App\nr=tk.Tk();a=App(r);r.update();r.after(300,r.destroy);r.mainloop()\n',encoding='utf8')
    wrapper=isolated/'check_environment.py'
    wrapper.write_text('import os,subprocess\nos.environ.update('+repr(env)+')\nos.environ.pop("YANGNING_DATA_ROOT",None)\nsubprocess.run(['+repr(str(python))+','+repr(str(check))+'],check=True)\n',encoding='utf8')
    run([sys.executable,str(wrapper)],cancel)
    if cancel.is_set():
        from media import Cancelled
        raise Cancelled()
    atomic_json(root/'current.json',{'version':STABLE_VERSION,'runtime_scope':'stable-v12.11','legacy_profile':True})
    shutil.copyfile(Path(__file__).with_name('desktop_launch.py'),root/'desktop_launch.py')
    from windows_shortcut import create_shortcuts
    previous=os.environ.get('YANGNING_SHORTCUT_NAME')
    try:
        os.environ['YANGNING_SHORTCUT_NAME']='杨宁视频工作室 测试版'
        create_shortcuts(python.with_name('pythonw.exe'),root/'desktop_launch.py',root)
    finally:
        if previous is None:os.environ.pop('YANGNING_SHORTCUT_NAME',None)
        else:os.environ['YANGNING_SHORTCUT_NAME']=previous
    atomic_json(root/'protected/isolated_restore.json',{'version':STABLE_VERSION,'platform':sys.platform,'setup_and_gui_checked':True,'profile':str(isolated/'profile'),'runtime':str(isolated/'runtime')})
    progress('v12.11独立恢复检查通过。关闭测试版，再从测试版快捷方式启动；素材和导出文件均保留。')
    return root
