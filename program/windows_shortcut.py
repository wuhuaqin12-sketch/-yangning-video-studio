"""Create Unicode shell links without Windows Script Host's ANSI Save path."""
import ctypes as C
import uuid
from pathlib import Path


def create_shortcuts(python, launcher, root):
    # IShellLinkW and IPersistFile use wide strings even on English Windows.
    ole=C.OleDLL('ole32');shell=C.OleDLL('shell32')
    GUID=C.c_ubyte*16
    def guid(value):return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)
    def check(hr):
        if hr<0:raise OSError(f'Windows shortcut error 0x{hr & 0xffffffff:08X}')
    def call(obj,slot,types,*args):
        table=C.cast(obj,C.POINTER(C.POINTER(C.c_void_p))).contents
        return C.WINFUNCTYPE(C.c_long,C.c_void_p,*types)(table[slot])(obj,*args)
    ole.CoInitialize.argtypes=[C.c_void_p];ole.CoInitialize.restype=C.c_long
    ole.CoCreateInstance.argtypes=[C.POINTER(GUID),C.c_void_p,C.c_ulong,C.POINTER(GUID),C.POINTER(C.c_void_p)]
    ole.CoCreateInstance.restype=C.c_long
    shell.SHGetFolderPathW.argtypes=[C.c_void_p,C.c_int,C.c_void_p,C.c_ulong,C.c_wchar_p]
    shell.SHGetFolderPathW.restype=C.c_long
    check(ole.CoInitialize(None))
    link=C.c_void_p();persist=C.c_void_p()
    try:
        check(ole.CoCreateInstance(C.byref(guid('00021401-0000-0000-c000-000000000046')),None,1,
                                   C.byref(guid('000214f9-0000-0000-c000-000000000046')),C.byref(link)))
        check(call(link,20,[C.c_wchar_p],str(python)))
        check(call(link,11,[C.c_wchar_p],'"'+str(launcher)+'"'))
        check(call(link,9,[C.c_wchar_p],str(root)))
        check(call(link,7,[C.c_wchar_p],'杨宁视频工作室'))
        check(call(link,0,[C.POINTER(GUID),C.POINTER(C.c_void_p)],
                   C.byref(guid('0000010b-0000-0000-c000-000000000046')),C.byref(persist)))
        for folder_id in (0x10,0x02): # DesktopDirectory, Programs
            path=C.create_unicode_buffer(32768)
            check(shell.SHGetFolderPathW(None,folder_id,None,0,path))
            directory=Path(path.value);directory.mkdir(parents=True,exist_ok=True)
            check(call(persist,6,[C.c_wchar_p,C.c_int],str(directory/'杨宁视频工作室.lnk'),1))
    finally:
        if persist.value:call(persist,2,[])
        if link.value:call(link,2,[])
        ole.CoUninitialize()
