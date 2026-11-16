"""Publish the exact Windows-tested candidate; never rebuild or overwrite stable assets."""
import hashlib,json,os,subprocess,sys,tempfile,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];version=json.loads((root/'release.json').read_text())['version']
repo=os.environ['GITHUB_REPOSITORY'];tag='v'+version
out=Path(os.environ['RUNNER_TEMP'])/'YangNingFormalAcceptance/package';archive=out/('YangNing_VideoStudio_Windows_'+version+'.zip')
info=json.loads((out/'latest.json').read_text())
assert info['version']==version and info['sha256']==hashlib.sha256(archive.read_bytes()).hexdigest() and info['size']==archive.stat().st_size
assert info['url']=='https://github.com/'+repo+'/releases/download/'+tag+'/'+archive.name
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    meta=json.loads(z.read('release.json'));assert meta['version']==version and meta.get('channel')!='test'
    assert meta['update_manifest_url']=='https://github.com/'+repo+'/releases/latest/download/latest.json'
    assert hashlib.sha256(z.read('recovery/v0.12.11-original.zip')).hexdigest()=='ac6b5a09c35d92c88c986334b959c4847540a0175b05d9cc0321235be60f200e'
def gh(*args,**kwargs):return subprocess.run(['gh',*args,'--repo',repo],**kwargs)
old=gh('release','view',tag,'--json','isDraft',capture_output=True,text=True)
notes=root/('RELEASE_'+version.replace('.','_')+'_ZH.md')
if old.returncode==0:
    if not json.loads(old.stdout)['isDraft']:
        print('Existing published version retained; nothing overwritten.');sys.exit(0)
else:
    gh('release','create',tag,'--target',os.environ['GITHUB_SHA'],'--title','杨宁视频工作室 '+version+' 正式版','--notes-file',str(notes),'--draft',check=True)
verification=out/('verification_'+version+'.json');record=json.loads(verification.read_text(encoding='utf8'))
assert record['sha256']==info['sha256'] and record['source_commit']==os.environ['GITHUB_SHA']
assert all(record[k] is True for k in ('old_check_update','old_download_verified','formal_gui','fresh_install','stable_restore','old_runtime_preserved','user_media_preserved'))
checks=out/'SHA256SUMS.txt';checks.write_text(info['sha256']+'  '+archive.name+'\n',encoding='utf8')
gh('release','upload',tag,str(archive),str(out/'latest.json'),str(checks),str(verification),str(notes),'--clobber',check=True)
with tempfile.TemporaryDirectory() as d:
    gh('release','download',tag,'--pattern',archive.name,'--dir',d,check=True)
    assert hashlib.sha256((Path(d)/archive.name).read_bytes()).hexdigest()==info['sha256']
gh('release','edit',tag,'--draft=false','--latest',check=True)
print('FORMAL_RELEASE_PUBLISHED',tag,info['sha256'])
