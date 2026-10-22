"""Stable desktop shortcut target; switch versions on next launch."""
import json,os,re,subprocess,sys
from pathlib import Path

def main():
    root=Path(__file__).resolve().parent
    version=json.loads((root/'current.json').read_text(encoding='utf8'))['version']
    if not isinstance(version,str) or not re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}',version):
        raise ValueError('软件版本指针无效，请重新安装。')
    program=root/'versions'/version/'program'
    env=os.environ.copy();env['YANGNING_INSTALL_ROOT']=str(root);env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8'
    python=root/'runtime'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    with (root/'launch.log').open('a',encoding='utf8') as log:
        flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        result=subprocess.run([str(python),str(program/'bootstrap.py')],cwd=program,env=env,stdout=log,stderr=log,**flags)
    if result.returncode:raise RuntimeError('启动失败。请查看 '+str(root/'launch.log'))

if __name__=='__main__':
    try:main()
    except Exception as e:
        if os.name=='nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,str(e),'杨宁视频工作室',16)
        else:raise
