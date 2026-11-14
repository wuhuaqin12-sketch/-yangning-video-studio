"""Actual Windows restore rehearsal in a disposable install/profile, no user data."""
import json,os,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'program'))
import stable_recovery as r
from desktop_update import atomic_json

def main():
    if sys.platform!='win32':raise RuntimeError('This rehearsal requires Windows.')
    sandbox=Path(os.environ['RUNNER_TEMP'])/'YangNingStableRecovery'
    root=sandbox/'install';profile=sandbox/'localappdata';settings=profile/'YangNingStudio'
    settings.mkdir(parents=True,exist_ok=True)
    root.mkdir(parents=True,exist_ok=True)
    archive=r.preserve_archive(root)
    stable=r.stage_stable(root,archive)
    atomic_json(root/'current.json',{'version':r.STABLE_VERSION})
    atomic_json(settings/'style_no_denoise.json',{})
    snap=r.snapshot(root,settings)
    atomic_json(root/'current.json',{'version':'0.12.15'})
    atomic_json(settings/'style_no_denoise.json',{'preview_incompatible':True})
    sentinel=sandbox/'USER_MEDIA_DO_NOT_DELETE.mp4';sentinel.write_bytes(b'user-media-sentinel')
    env=os.environ.copy();env['YANGNING_INSTALL_ROOT']=str(root);env['LOCALAPPDATA']=str(profile)
    def healthcheck(target):
        subprocess.run([sys.executable,str(target/'program/bootstrap.py'),'--setup-only'],env=env,check=True)
        python=root/'runtime/Scripts/python.exe'
        smoke=sandbox/'gui_smoke.py'
        smoke.write_text("import sys,tkinter as tk\nfrom pathlib import Path\nsys.path.insert(0,sys.argv[1])\nfrom media import executable\nimport subprocess\nfor n in ('ffmpeg','ffprobe'): subprocess.run([executable(n),'-version'],check=True,capture_output=True)\nfrom app import App\nroot=tk.Tk()\napp=App(root)\nroot.update()\nroot.after(500,root.destroy)\nroot.mainloop()\nprint('STABLE_GUI_START_PASS')\n",encoding='utf8')
        subprocess.run([str(python),str(smoke),str(target/'program')],env=env,check=True,timeout=90)
        return {'platform':sys.platform,'passed':True,'checks':['setup','ffmpeg','ffprobe','Tk App initialization']}
    r.restore(root,settings,archive,healthcheck,snap)
    assert json.loads((root/'current.json').read_text())['version']==r.STABLE_VERSION
    assert sentinel.read_bytes()==b'user-media-sentinel'
    assert json.loads((settings/'style_no_denoise.json').read_text())=={}
    print('WINDOWS_STABLE_RESTORE_PASS')
if __name__=='__main__':main()
