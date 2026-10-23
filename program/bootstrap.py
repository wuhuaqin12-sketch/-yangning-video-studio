"""First launch installs a private environment, then starts the local desktop GUI."""
import os,sys,subprocess,venv,shutil,struct,hashlib,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parent;ENV=(Path(os.environ['YANGNING_INSTALL_ROOT'])/'runtime' if os.environ.get('YANGNING_INSTALL_ROOT') else ROOT/'.venv');PY=ENV/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
def invoke(args,required=True):
    env=os.environ.copy();env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8'
    r=subprocess.run(args,cwd=ROOT,env=env)
    if required and r.returncode:raise RuntimeError('安装未完成，请保留窗口中的错误信息。')
    return r.returncode

def runtime_health():
    if not (ENV/'pyvenv.cfg').is_file() or not PY.is_file():return False
    try:
        result=subprocess.run([str(PY),'-I',str(ROOT/'python_check.py'),'--venv',str(ENV)],cwd=ROOT,capture_output=True,timeout=30)
        if result.returncode:
            message=(result.stderr or result.stdout or b'').decode('utf8',errors='replace')[-1500:]
            if message:print('Runtime check:',message)
        return result.returncode==0
    except (OSError,subprocess.TimeoutExpired):return False

def ensure_runtime():
    if runtime_health():return
    # Keep the failed attempt for diagnosis, without touching project folders.
    # Installation is invoked with a validated base Python, not this broken EXE.
    if ENV.exists():
        if Path(sys.executable).resolve()==PY.resolve():
            raise RuntimeError('运行环境需要修复，请关闭软件并运行新版 INSTALL.bat。')
        backup=ENV.with_name(ENV.name+'.failed_'+uuid.uuid4().hex[:10])
        try:ENV.rename(backup)
        except PermissionError as e:raise RuntimeError('请先关闭所有杨宁视频工作室窗口，再运行 INSTALL.bat；原文件未删除。') from e
        print('Previous incomplete runtime preserved:',backup)
    print('Preparing local Python environment...')
    venv.EnvBuilder(with_pip=True).create(ENV)
    if not runtime_health():raise RuntimeError('新运行环境检查失败；未启用软件。请保留此窗口中的错误信息。')

def main():
    from python_check import current_reason
    reason=current_reason()
    if reason:raise RuntimeError(reason)
    if os.name=='nt' and struct.calcsize('P')!=8:raise RuntimeError('请使用64位Python 3.12；当前Python为32位。无需安装编译器。')
    ensure_runtime()
    marker=ENV/('setup_'+hashlib.sha256((ROOT/'requirements.txt').read_bytes()).hexdigest()[:16]+'.ok')
    if not marker.exists():
        print('First launch requires internet for local dependencies; no cloud API or login.')
        invoke([str(PY),'-m','pip','install','--upgrade','--only-binary=:all:','pip'],False)
        invoke([str(PY),'-m','pip','install','--only-binary=:all:','-r',str(ROOT/'requirements.txt')])
        from media import executable
        try:executable('ffmpeg');executable('ffprobe')
        except RuntimeError:
            if os.name=='nt' and shutil.which('winget'):
                invoke(['winget','install','--exact','--id','Gyan.FFmpeg','--source','winget'])
                executable('ffmpeg');executable('ffprobe')
            else:raise RuntimeError('未找到 FFmpeg。请把 ffmpeg.exe 与 ffprobe.exe 放入 program/tools，再打开工具。')
        marker.write_text('0.2',encoding='ascii')
    # Reference-guided alignment is installed lazily inside its cancellable worker.
    if '--setup-only' not in sys.argv:invoke([str(PY),str(ROOT/'app.py')])
if __name__=='__main__':
    try:main()
    except Exception as e:
        print('\nERROR:',e)
        if not os.environ.get('YANGNING_INSTALL_ROOT'):input('Press Enter to close...')
        sys.exit(1)
