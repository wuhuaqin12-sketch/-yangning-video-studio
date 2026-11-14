"""Exercise the new Tk panel and test-channel installer on real Windows."""
import json,os,subprocess,sys,tempfile,zipfile
from pathlib import Path
repo=Path(__file__).resolve().parents[1]
sandbox=Path(os.environ['RUNNER_TEMP'])/'YangNingNextAcceptance';sandbox.mkdir(exist_ok=True)
os.environ['LOCALAPPDATA']=str(sandbox/'localappdata')
os.environ['YANGNING_DATA_ROOT']=str(sandbox/'gui_profile')
sys.path.insert(0,str(repo/'program'))

def main():
    import tkinter as tk
    from app import App
    root=tk.Tk();app=App(root);panel=app.sequence_panel
    assert app.v['burn'].get() is False
    panel.enabled.set(True);panel.v['intro_enabled'].set(True);panel.v['outro_enabled'].set(True)
    panel.mode.set('横版＋竖版');panel.change_mode();panel.update();root.update()
    assert app.sequence_settings['output_mode']=='both'
    assert panel.cover_l.winfo_ismapped() and panel.cover_p.winfo_ismapped()
    assert not panel.cover_single.winfo_ismapped()
    panel.auto_save();assert panel.autosave.is_file()
    try:
        from PIL import ImageGrab
        ImageGrab.grab().save(sandbox/'new_ui.png')
    except Exception as e:print('Screenshot unavailable:',e)
    root.destroy();print('NEW_UI_SMOKE_PASS',flush=True)
    # Keep a fake production install and old settings as non-modification sentinels.
    local=Path(os.environ['LOCALAPPDATA']);prod=local/'YangNingStudioDesktop';prod.mkdir(parents=True)
    (prod/'current.json').write_text('{"version":"0.12.11"}')
    settings=local/'YangNingStudio';settings.mkdir();(settings/'user_settings.json').write_text('keep')
    package_dir=sandbox/'packages'
    subprocess.run([sys.executable,str(repo/'make_release.py'),'--test-package','--version','0.13.0','--package-url','https://example.invalid/test.zip','--manifest-url','https://example.invalid/latest.json','--output',str(package_dir)],check=True)
    package=package_dir/'YangNing_VideoStudio_Windows_0.13.0.zip'
    with zipfile.ZipFile(package) as z:
        release=json.loads(z.read('release.json'));assert release['channel']=='test';assert release['update_manifest_url']==''
        for n in ('ffmpeg','ffprobe'):assert z.getinfo('program/tools/'+n+'.exe').file_size>1000000
        unpack=sandbox/'unpacked';z.extractall(unpack)
    subprocess.run([sys.executable,str(unpack/'program/install_desktop.py'),'--quiet'],check=True)
    preview=local/'YangNingStudioDesktopPreview'
    assert (preview/'preview_profile.json').exists();assert (preview/'runtime/Scripts/python.exe').exists()
    assert json.loads((prod/'current.json').read_text())['version']=='0.12.11'
    assert (settings/'user_settings.json').read_text()=='keep'
    assert not (preview/'update_config.json').exists()
    print('ISOLATED_TEST_INSTALL_PASS',flush=True)
if __name__=='__main__':main()
