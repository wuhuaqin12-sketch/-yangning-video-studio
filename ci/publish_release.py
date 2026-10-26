"""Build and publish a release only after required CI jobs have passed."""
import json,os,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parent.parent
data=json.loads((root/'release.json').read_text());base_version=data['version']
repo=os.environ['GITHUB_REPOSITORY']
# Choose a new patch version without requiring manual edits to release.json.
# Published releases are immutable: never overwrite an existing version.
def next_version():
    import re
    def version_tuple(value):
        if not re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}',value):raise ValueError('Invalid version: '+str(value))
        return tuple(map(int,value.split('.')))
    base=version_tuple(base_version)
    result=subprocess.run(['gh','release','list','--repo',repo,'--limit','100','--json','tagName,isDraft'],capture_output=True,text=True,check=True)
    published=[]
    for entry in json.loads(result.stdout):
        if entry.get('isDraft'):continue
        tag_name=entry.get('tagName','')
        try:
            if tag_name.startswith('v'):published.append(version_tuple(tag_name[1:]))
        except ValueError:pass
    if not published:return base_version
    latest=max(published)
    if base>latest:return base_version
    return '.'.join(map(str,(latest[0],latest[1],latest[2]+1)))
version=next_version()
tag='v'+version
out=Path(os.environ['RUNNER_TEMP'])/'yangning-release'
manifest_url='https://github.com/'+repo+'/releases/latest/download/latest.json'
package_url='https://github.com/'+repo+'/releases/download/'+tag+'/YangNing_VideoStudio_Windows_'+version+'.zip'
subprocess.run([sys.executable,str(root/'make_release.py'),'--version',version,'--package-url',package_url,'--manifest-url',manifest_url,'--output',str(out),'--notes','主页面新增成片倍速选择；所有配音语言默认1.1倍，可手动选择，保持音调并同步画面与字幕。'],check=True)
def gh(*args,**kwargs):return subprocess.run(['gh',*args,'--repo',repo],**kwargs)
result=gh('release','view',tag,'--json','isDraft',capture_output=True,text=True)
if result.returncode==0:
    if not json.loads(result.stdout)['isDraft']:
        print('This version is already published; existing release left unchanged.')
        sys.exit(0)
else:
    gh('release','create',tag,'--target',os.environ['GITHUB_SHA'],'--title','杨宁视频工作室 '+version,'--notes','主页面新增成片倍速选择；所有配音语言默认1.1倍，可选0.75至2.0倍，保持音调。切换语言保留所选倍速。下载Windows ZIP后完整解压运行INSTALL.bat；已安装用户可在软件中检查更新。','--draft',check=True)
gh('release','upload',tag,str(out/('YangNing_VideoStudio_Windows_'+version+'.zip')),str(out/'latest.json'),'--clobber',check=True)
gh('release','edit',tag,'--draft=false','--latest',check=True)
print('Release published:',tag)

