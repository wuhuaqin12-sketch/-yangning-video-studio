"""Isolated, pinned CPU runtime for reference-guided alignment on Windows."""
import json,os,subprocess,sys,uuid,venv
from pathlib import Path

CPU_PACKAGES=['torch==2.6.0','torchaudio==2.6.0']
PROBE="import torch,torchaudio,stable_whisper; assert torch.__version__.split('+')[0]=='2.6.0'; assert torch.version.cuda is None; print(torch.zeros(1)+1)"

def runtime_path():
    return Path(os.environ.get('LOCALAPPDATA',Path.home()/'.cache'))/'YangNingStudio'/'alignment_cpu_260_v1'

def python_path(root):
    return root/('Scripts/python.exe' if os.name=='nt' else 'bin/python')

def healthy(python):
    if not python.is_file():return False
    try:
        r=subprocess.run([str(python),'-I','-c',PROBE],capture_output=True,timeout=90)
        if r.returncode:print(r.stderr.decode('utf8',errors='replace')[-3000:],flush=True)
        return r.returncode==0
    except (OSError,subprocess.TimeoutExpired):return False

def prepare(status,force=False):
    root=runtime_path();python=python_path(root)
    if not force and healthy(python):return python
    status('准备独立CPU语音环境；首次需要联网下载组件，请勿重复启动任务')
    root.parent.mkdir(parents=True,exist_ok=True)
    if root.exists():root.rename(root.with_name(root.name+'.backup_'+uuid.uuid4().hex[:8]))
    venv.EnvBuilder(with_pip=True).create(root)
    constraints=root/'constraints.txt'
    constraints.write_text('torch==2.6.0\ntorchaudio==2.6.0\nnumpy<3\n',encoding='ascii')
    subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','--only-binary=:all:',*CPU_PACKAGES,'--index-url','https://download.pytorch.org/whl/cpu'],check=True)
    subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','--only-binary=:all:','--no-binary=stable-ts,openai-whisper','-c',str(constraints),'stable-ts==2.19.1'],check=True)
    status('检查CPU语音组件能否正常加载')
    if not healthy(python):raise RuntimeError('CPU语音环境自检失败。若日志仍含c10.dll，请安装或修复微软Visual C++ 2015–2022 x64运行库并重启。https://aka.ms/vs/17/release/vc_redist.x64.exe')
    return python

def launch(request):
    folder=Path(request).parent
    def status(message):
        print(message,flush=True)
        tmp=folder/'alignment_progress.writing';tmp.write_text(message,encoding='utf8');tmp.replace(folder/'alignment_progress.txt')
    python=prepare(status)
    env=os.environ.copy();env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    return subprocess.call([str(python),str(Path(__file__).with_name('multilingual.py')),str(request),'--alignment-ready'],env=env)

if __name__=='__main__':
    try:
        prepare(lambda message:print(message,flush=True),force='--repair' in sys.argv)
        print('CPU alignment runtime OK. Open START.bat to retry.')
    except Exception as exc:
        print(str(exc),file=sys.stderr);sys.exit(1)
