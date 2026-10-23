"""Versioned per-user installs. HTTPS + digest verification; never replace user data."""
import hashlib,json,os,re,shutil,stat,tempfile,urllib.parse,urllib.request,uuid,zipfile
from pathlib import Path

APP_VERSION='0.11.5'
MAX_PACKAGE=200*1024*1024
MAX_EXTRACTED=600*1024*1024

def version_tuple(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}',value):
        raise ValueError('版本号格式应为数字，例如 0.11.0。')
    return tuple(map(int,value.split('.')))

def install_root():
    return Path(os.environ.get('YANGNING_INSTALL_ROOT') or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'YangNingStudioDesktop')

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def https_url(value):
    if not isinstance(value,str):raise ValueError('更新地址无效。')
    u=urllib.parse.urlsplit(value)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.fragment:
        raise ValueError('更新地址必须是没有账户密码的 HTTPS 地址。')
    return value

class HTTPSOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        https_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch(url,limit,destination=None,cancel=None):
    opener=urllib.request.build_opener(HTTPSOnly())
    req=urllib.request.Request(https_url(url),headers={'User-Agent':'YangNingStudio/'+APP_VERSION})
    with opener.open(req,timeout=20) as response:
        https_url(response.url)
        size=0;parts=[]
        output=open(destination,'wb') if destination else None
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    from media import Cancelled
                    raise Cancelled()
                block=response.read(1024*1024)
                if not block:break
                size+=len(block)
                if size>limit:raise ValueError('更新文件超过大小限制。')
                if output:output.write(block)
                else:parts.append(block)
        finally:
            if output:output.close()
    return size if destination else b''.join(parts)

def read_config(root=None):
    root=Path(root or install_root())
    try:config=json.loads((root/'update_config.json').read_text(encoding='utf8'))
    except FileNotFoundError:return {'manifest_url':'','auto_check':True}
    if not isinstance(config,dict):raise ValueError('更新设置损坏，请重新设置更新地址。')
    return config

def save_config(url,root=None):
    root=Path(root or install_root())
    atomic_json(root/'update_config.json',{'manifest_url':https_url(url) if url else '', 'auto_check':True})

def check_update(root=None,loader=fetch):
    config=read_config(root)
    if not config.get('manifest_url'):return None
    data=json.loads(loader(config['manifest_url'],64*1024).decode('utf-8-sig'))
    if not isinstance(data,dict) or data.get('format')!='YangNingStudioUpdate' or data.get('schema')!=1:
        raise ValueError('这不是有效的杨宁视频工作室更新信息。')
    version_tuple(data.get('version'))
    https_url(data.get('url'))
    if not re.fullmatch(r'[0-9a-fA-F]{64}',str(data.get('sha256',''))):
        raise ValueError('更新缺少 SHA-256 校验信息。')
    if type(data.get('size')) is not int or not 0<data['size']<=MAX_PACKAGE:
        raise ValueError('更新文件大小无效。')
    data['notes']=str(data.get('notes',''))[:4000]
    return data if version_tuple(data['version'])>version_tuple(APP_VERSION) else {}

def stage_package(archive,root,expected_version=None):
    root=Path(root);versions=root/'versions';versions.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix='.staging-',dir=versions))
    try:
        with zipfile.ZipFile(archive) as z:
            infos=z.infolist()
            if len(infos)>5000 or sum(i.file_size for i in infos)>MAX_EXTRACTED:
                raise ValueError('更新包展开后过大。')
            names=set()
            for i in infos:
                name=i.filename
                parts=name.replace('\\','/').split('/')
                if name.startswith(('/','\\')) or '\\' in name or ':' in name or '..' in parts:
                    raise ValueError('更新包含不安全的文件路径。')
                for part in filter(None,parts):
                    stem=part.split('.')[0].upper()
                    if part.endswith((' ','.')) or stem in {'CON','PRN','AUX','NUL',*[f'COM{n}' for n in range(1,10)],*[f'LPT{n}' for n in range(1,10)]}:
                        raise ValueError('更新包含无效的 Windows 文件名。')
                if stat.S_ISLNK(i.external_attr>>16):raise ValueError('更新包不允许符号链接。')
                key=name.casefold().rstrip('/')
                if key in names:raise ValueError('更新包含重复文件名。')
                names.add(key)
                if any(p.casefold() in ('.venv','__pycache__') for p in parts):
                    raise ValueError('更新包不应包含运行环境或缓存。')
            z.extractall(temp)
        metadata=json.loads((temp/'release.json').read_text(encoding='utf8'))
        version=metadata['version'];version_tuple(version)
        if metadata.get('app')!='YangNingStudio' or metadata.get('schema')!=1:
            raise ValueError('更新包不是本软件。')
        if expected_version and version!=expected_version:raise ValueError('更新包版本与发布信息不一致。')
        for name in ('app.py','bootstrap.py','desktop_update.py','desktop_launch.py','requirements.txt'):
            if not (temp/'program'/name).is_file():raise ValueError('更新包不完整：'+name)
        target=versions/version
        if target.exists():raise ValueError('此版本已经安装，请直接重新打开桌面软件。')
        os.replace(temp,target)
        return version,target
    finally:
        if temp.exists():shutil.rmtree(temp)

def activate(root,version):
    version_tuple(version);root=Path(root)
    if not (root/'versions'/version/'program'/'app.py').is_file():
        raise ValueError('尚未准备好要启用的版本。')
    previous=None
    try:previous=json.loads((root/'current.json').read_text())['version']
    except (OSError,ValueError,KeyError):pass
    atomic_json(root/'current.json',{'version':version,'previous_version':previous})

def download_update(info,root=None,loader=None,cancel=None):
    if loader is None:loader=lambda url,limit,path:fetch(url,limit,path,cancel)
    root=Path(root or install_root());root.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(suffix='.zip',dir=root);os.close(fd);archive=Path(name)
    try:
        loader(info['url'],MAX_PACKAGE,archive)
        if archive.stat().st_size!=info['size']:raise ValueError('更新下载不完整，原版本未改变。')
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest!=info['sha256'].lower():raise ValueError('更新文件校验失败，原版本未改变。')
        return stage_package(archive,root,info['version'])
    finally:archive.unlink(missing_ok=True)
