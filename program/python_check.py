"""Validate Windows Python before it creates our AppData runtime."""
import os,struct,sys
from pathlib import Path

def store_path(path):
    parts=str(path).lower().replace('\\','/').split('/')
    return 'windowsapps' in parts or any(p.startswith('pythonsoftwarefoundation.python') for p in parts)
def rejection_reason(version,bits,paths):
    if not (3,10)<=tuple(version[:2])<=(3,13):return '需要64位 Python 3.10–3.13，推荐3.12。'
    if bits!=64:return '请使用64位Python。'
    if any(store_path(path) for path in paths):
        return '商店版Python会重定向安装目录，请通过 INSTALL.bat 准备普通版Python。'
    return ''

def current_reason():
    return rejection_reason(sys.version_info,struct.calcsize('P')*8,(sys.executable,getattr(sys,'_base_executable',''),sys.base_prefix))

def main():
    reason=current_reason()
    if reason:raise RuntimeError(reason)
    import tkinter,venv,ensurepip
    if '--venv' in sys.argv:
        expected=Path(sys.argv[sys.argv.index('--venv')+1]).resolve()
        if not (expected/'pyvenv.cfg').is_file():raise RuntimeError('缺少 pyvenv.cfg')
        if Path(sys.prefix).resolve()!=expected or sys.prefix==sys.base_prefix:raise RuntimeError('运行环境目录不一致')
        import pip

if __name__=='__main__':
    try:main()
    except Exception as e:print(str(e),file=sys.stderr);sys.exit(1)
