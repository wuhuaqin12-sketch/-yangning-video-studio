"""Exercise the new Tk panel and test-channel installer on real Windows."""
import json,os,subprocess,sys,tempfile,zipfile
from pathlib import Path
repo=Path(__file__).resolve().parents[1]
sandbox=Path(os.environ['RUNNER_TEMP'])/'YangNingNextAcceptance';sandbox.mkdir(exist_ok=True)
os.environ['LOCALAPPDATA']=str(sandbox/'localappdata')
os.environ['YANGNING_DATA_ROOT']=str(sandbox/'gui_profile')
sys.path.insert(0,str(repo/'program'))

def p_label_present(parent,text):
    for child in parent.winfo_children():
        try:
            if child.cget('text')==text:return True
        except Exception:pass
        if p_label_present(child,text):return True
    return False

def main():
    import tkinter as tk
    from app import App
    root=tk.Tk();app=App(root);panel=app.sequence_panel
    def widgets(parent):
        for child in parent.winfo_children():
            yield child;yield from widgets(child)
    labels=[w.cget('text') for w in widgets(root) if w.winfo_class()=='TButton']
    for label in ('降噪 / 人声分离 / 试听','停顿 / 速度','标题 / 字幕 / 封面'):assert labels.count(label)==1
    assert app.v['burn'].get() is False
    assert panel.v['background_audio'].get()==''
    assert p_label_present(root, '片头背景音乐（可选）')
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
    subprocess.run([sys.executable,str(repo/'make_release.py'),'--test-package','--version','0.13.2','--package-url','https://example.invalid/test.zip','--manifest-url','https://example.invalid/latest.json','--output',str(package_dir)],check=True)
    package=package_dir/'YangNing_VideoStudio_Windows_0.13.2.zip'
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
    # Exercise the actual GUI recovery backend, not only the low-level mock tests.
    recovery=sandbox/'run_installed_recovery.py'
    recovery.write_text('import os,sys,threading\nfrom pathlib import Path\nos.environ["YANGNING_INSTALL_ROOT"]='+repr(str(preview))+'\nos.environ["YANGNING_DATA_ROOT"]='+repr(str(preview/'profile/YangNingStudio'))+'\nsys.path.insert(0,'+repr(str(preview/'versions/0.13.2/program'))+')\nfrom recovery_ui_backend import restore_isolated\nrestore_isolated(threading.Event(),print)\n',encoding='utf8')
    subprocess.run([sys.executable,str(recovery)],check=True)
    restored=json.loads((preview/'current.json').read_text())
    assert restored['version']=='0.12.11';assert restored['runtime_scope']=='stable-v12.11'
    assert (preview/'runtime/Scripts/python.exe').exists()
    assert (preview/'stable-v12.11/runtime/Scripts/python.exe').exists()
    assert json.loads((prod/'current.json').read_text())['version']=='0.12.11'
    assert (settings/'user_settings.json').read_text()=='keep'
    print('INTEGRATED_STABLE_RECOVERY_PASS',flush=True)
if __name__=='__main__':main()
