"""First launch installs a private environment, then starts the local desktop GUI."""
import os,sys,subprocess,venv,shutil,struct,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent;ENV=(Path(os.environ['YANGNING_INSTALL_ROOT'])/'runtime' if os.environ.get('YANGNING_INSTALL_ROOT') else ROOT/'.venv');PY=ENV/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
def invoke(args,required=True):
    env=os.environ.copy();env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8'
    r=subprocess.run(args,cwd=ROOT,env=env)
    if required and r.returncode:raise RuntimeError('安装未完成，请保留窗口中的错误信息。')
    return r.returncode

def main():
    if not (3,10)<=sys.version_info[:2]<=(3,13):raise RuntimeError('需要 Python 3.10–3.13，推荐3.12。')
    if os.name=='nt' and struct.calcsize('P')!=8:raise RuntimeError('请使用64位Python 3.12；当前Python为32位。无需安装编译器。')
    if not PY.exists():print('Preparing local Python environment...');venv.EnvBuilder(with_pip=True).create(ENV)
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
