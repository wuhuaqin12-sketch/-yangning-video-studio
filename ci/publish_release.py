"""Build and publish a release only after required CI jobs have passed."""
import json,os,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parent.parent
data=json.loads((root/'release.json').read_text());version=data['version']
repo=os.environ['GITHUB_REPOSITORY'];tag='v'+version
out=Path(os.environ['RUNNER_TEMP'])/'yangning-release'
manifest_url='https://github.com/'+repo+'/releases/latest/download/latest.json'
package_url='https://github.com/'+repo+'/releases/download/'+tag+'/YangNing_VideoStudio_Windows_'+version+'.zip'
subprocess.run([sys.executable,str(root/'make_release.py'),'--version',version,'--package-url',package_url,'--manifest-url',manifest_url,'--output',str(out),'--notes','新增可选声音处理：温和降噪、独立人声分离、原声对比试听；保留素材和成片。'],check=True)
def gh(*args,**kwargs):return subprocess.run(['gh',*args,'--repo',repo],**kwargs)
result=gh('release','view',tag,'--json','isDraft',capture_output=True,text=True)
if result.returncode==0:
    if not json.loads(result.stdout)['isDraft']:
        print('This version is already published; existing release left unchanged.')
        sys.exit(0)
else:
    gh('release','create',tag,'--target',os.environ['GITHUB_SHA'],'--title','杨宁视频工作室 '+version,'--notes','下载 Windows ZIP，完整解压后运行 INSTALL.bat。之后从桌面打开，并在软件里更新。','--draft',check=True)
gh('release','upload',tag,str(out/('YangNing_VideoStudio_Windows_'+version+'.zip')),str(out/'latest.json'),'--clobber',check=True)
gh('release','edit',tag,'--draft=false','--latest',check=True)
print('Release published:',tag)
