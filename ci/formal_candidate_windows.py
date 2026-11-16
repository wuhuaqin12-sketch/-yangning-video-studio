"""Build/install through the old update API; protect the actual stable runtime."""
import hashlib,json,os,subprocess,sys,zipfile
from pathlib import Path
repo=Path(__file__).resolve().parents[1];sys.path.insert(0,str(repo/'program'))
from desktop_update import atomic_json
from stable_recovery import preserve_archive,stage_stable

VERSION='0.14.1'
def main():
    sandbox=Path(os.environ['RUNNER_TEMP'])/'YangNingFormalAcceptance';sandbox.mkdir(exist_ok=True)
    root=sandbox/'install';local=sandbox/'localappdata';settings=local/'YangNingStudio';settings.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env['LOCALAPPDATA']=str(local);env['YANGNING_INSTALL_ROOT']=str(root);env['YANGNING_DATA_ROOT']=str(settings)
    os.environ.update({'LOCALAPPDATA':str(local),'YANGNING_INSTALL_ROOT':str(root),'YANGNING_DATA_ROOT':str(settings)})
    archive=preserve_archive(root,repo/'recovery/v0.12.11-original.zip');stable=stage_stable(root,archive)
    atomic_json(root/'current.json',{'version':'0.12.11'});atomic_json(settings/'style_no_denoise.json',{'title':'保留原设置'})
    sentinel=sandbox/'USER_VIDEO_DO_NOT_DELETE.mp4';sentinel.write_bytes(b'original user media')
    subprocess.run([sys.executable,str(stable/'program/bootstrap.py'),'--setup-only'],env=env,check=True)
    old_python=root/'runtime/Scripts/python.exe';old_health=(root/'runtime/pyvenv.cfg').read_bytes()
    package_dir=sandbox/'package';package_dir.mkdir(exist_ok=True)
    url='https://github.com/wuhuaqin12-sketch/-yangning-video-studio/releases/download/v'+VERSION+'/YangNing_VideoStudio_Windows_'+VERSION+'.zip'
    feed='https://github.com/wuhuaqin12-sketch/-yangning-video-studio/releases/latest/download/latest.json'
    subprocess.run([sys.executable,str(repo/'make_release.py'),'--version',VERSION,'--package-url',url,'--manifest-url',feed,'--output',str(package_dir),'--notes','简洁主页面、默认竖版、片头音乐记忆、字号位置修复、统一手机兼容编码、更新备份与稳定版恢复。'],check=True)
    package=package_dir/('YangNing_VideoStudio_Windows_'+VERSION+'.zip')
    info=json.loads((package_dir/'latest.json').read_text())
    with zipfile.ZipFile(package) as z:
        meta=json.loads(z.read('release.json'));assert meta['version']==VERSION and meta.get('channel')!='test' and meta['update_manifest_url']==feed
        for name in ('ffmpeg.exe','ffprobe.exe'):assert z.getinfo('program/tools/'+name).file_size>1000000
    updater=sandbox/'old_update.py'
    updater.write_text('import sys,json,shutil\nfrom pathlib import Path\nsys.path.insert(0,'+repr(str(stable/'program'))+')\nfrom desktop_update import download_update,activate,save_config,check_update\nroot=Path('+repr(str(root))+')\ninfo='+repr(info)+'\nsave_config('+repr(feed)+',root)\nassert check_update(root,lambda *_:json.dumps(info).encode())["version"]=='+repr(VERSION)+'\nversion,target=download_update(info,root,lambda u,l,p:shutil.copyfile('+repr(str(package))+',p))\nimport subprocess\nsubprocess.run(['+repr(str(old_python))+',str(target/"program/bootstrap.py"),"--setup-only"],check=True)\nassert json.loads((root/"current.json").read_text())["version"]=="0.12.11"\nactivate(root,version)\n',encoding='utf8')
    subprocess.run([sys.executable,str(updater)],env=env,check=True)
    python=root/'runtimes'/VERSION/'Scripts/python.exe';assert python.exists()
    assert (root/'runtime/pyvenv.cfg').read_bytes()==old_health
    assert json.loads((root/'current.json').read_text())['version']==VERSION
    assert list((root/'backups').glob('*/manifest.json'))
    assert json.loads((settings/'style_no_denoise.json').read_text())['title']=='保留原设置'
    smoke=sandbox/'gui.py'
    smoke.write_text('import sys,tkinter as tk\nsys.path.insert(0,'+repr(str(root/'versions'/VERSION/'program'))+')\nfrom app import App\nfrom PIL import ImageGrab\nr=tk.Tk();a=App(r);r.update();assert a.sequence_panel.value()["output_mode"]=="portrait"\nassert not a.sequence_panel.controls.winfo_ismapped()\na.sequence_panel.appearance_open.set(True);a.sequence_panel.update();r.update();assert a.sequence_panel.layouts.tab(0,"state")=="hidden"\nImageGrab.grab().save('+repr(str(sandbox/'formal-settings.png'))+')\na.sequence_panel.appearance_open.set(False);a.sequence_panel.update();r.update();ImageGrab.grab().save('+repr(str(sandbox/'formal-main.png'))+')\nr.after(300,r.destroy);r.mainloop()\nprint("FORMAL_INSTALLED_GUI_PASS")\n',encoding='utf8')
    subprocess.run([str(python),str(smoke)],env=env,check=True)
    # Recovery must act on this formal install, never redirect to Preview.
    restore=sandbox/'restore.py';restore.write_text('import sys,threading\nsys.path.insert(0,'+repr(str(root/'versions'/VERSION/'program'))+')\nfrom recovery_ui_backend import restore_isolated\nrestore_isolated(threading.Event(),print)\n',encoding='utf8')
    subprocess.run([str(python),str(restore)],env=env,check=True)
    restored=json.loads((root/'current.json').read_text());assert restored['version']=='0.12.11' and restored['legacy_profile']
    assert (root/'runtimes'/VERSION/'Scripts/python.exe').exists() and (root/'runtime/pyvenv.cfg').read_bytes()==old_health
    assert sentinel.read_bytes()==b'original user media'
    # Run the actual first-time installer separately from the update path.
    fresh=sandbox/'fresh-install';fresh_env=env.copy();fresh_env['YANGNING_INSTALL_ROOT']=str(fresh);fresh_env['LOCALAPPDATA']=str(sandbox/'fresh-local');fresh_env['YANGNING_DATA_ROOT']=str(sandbox/'fresh-profile')
    subprocess.run([sys.executable,str(root/'versions'/VERSION/'program/install_desktop.py'),'--quiet'],env=fresh_env,check=True)
    assert json.loads((fresh/'current.json').read_text())['version']==VERSION
    assert json.loads((fresh/'update_config.json').read_text())['manifest_url']==feed
    assert (fresh/'runtimes'/VERSION/'Scripts/pythonw.exe').exists()
    assert not (fresh/'preview_profile.json').exists()
    assert (fresh/'protected/v0.12.11-original.zip').exists()
    (sandbox/'formal-acceptance.json').write_text(json.dumps(dict(version=VERSION,old_check_update=True,old_download_verified=True,formal_gui=True,fresh_install=True,stable_restore=True,old_runtime_preserved=True,user_media_preserved=True,sha256=hashlib.sha256(package.read_bytes()).hexdigest()),indent=2),encoding='utf8')
    evidence=json.loads((sandbox/'formal-acceptance.json').read_text(encoding='utf8'))
    evidence['source_commit']=os.environ.get('GITHUB_SHA','')
    evidence['mobile_checks']=json.loads((sandbox/'mobile-compatibility.json').read_text(encoding='utf8'))
    evidence['stable_original_sha256']='ac6b5a09c35d92c88c986334b959c4847540a0175b05d9cc0321235be60f200e'
    (package_dir/('verification_'+VERSION+'.json')).write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
    print('FORMAL_CHECK_UPDATE_INSTALL_AND_STABLE_RECOVERY_PASS',flush=True)

if __name__=='__main__':main()
