"""External recovery remains usable when the preview GUI cannot start."""
import os,sys,threading
from pathlib import Path
os.environ['YANGNING_INSTALL_ROOT']=str(Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'YangNingStudioDesktopPreview')
os.environ['YANGNING_DATA_ROOT']=str(Path(os.environ['YANGNING_INSTALL_ROOT'])/'profile/YangNingStudio')
if __name__=='__main__':
    try:
        from recovery_ui_backend import restore_isolated
        print(restore_isolated(threading.Event(),lambda s:print(s,flush=True)))
    except Exception as e:
        print('恢复未完成，原素材和原稳定版未删除：',e)
        sys.exit(1)
