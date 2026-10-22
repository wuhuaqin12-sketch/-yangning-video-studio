"""Publisher helper: build app ZIP + HTTPS update manifest with exact digest."""
import argparse,hashlib,json,re,zipfile
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'program'))
from desktop_update import https_url,version_tuple

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--version',required=True)
    p.add_argument('--package-url',required=True)
    p.add_argument('--manifest-url',required=True)
    p.add_argument('--notes',default='')
    p.add_argument('--output',required=True)
    args=p.parse_args();version_tuple(args.version)
    https_url(args.package_url);https_url(args.manifest_url)
    root=Path(__file__).resolve().parent;out=Path(args.output).resolve()
    if root==out or root in out.parents:raise ValueError('输出目录请放在源码目录以外。')
    out.mkdir(parents=True,exist_ok=True)
    archive=out/('YangNing_VideoStudio_Windows_'+args.version+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for f in root.rglob('*'):
            if not f.is_file() or any(part in ('.venv','__pycache__','.git') for part in f.parts) or f.suffix=='.pyc':continue
            name=f.relative_to(root).as_posix();body=f.read_bytes()
            if name=='release.json':
                body=json.dumps(dict(app='YangNingStudio',schema=1,version=args.version,update_manifest_url=args.manifest_url)).encode()
            if name=='program/desktop_update.py':
                body=re.sub(rb"APP_VERSION='[^']+'",("APP_VERSION='"+args.version+"'").encode(),body)
            if name=='program/engine.py':
                body=re.sub(rb"VERSION='[^']+'",("VERSION='"+args.version+"'").encode(),body)
            z.writestr(name,body)
    info=dict(format='YangNingStudioUpdate',schema=1,version=args.version,url=args.package_url,
              size=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),notes=args.notes)
    (out/'latest.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8')
    print(archive);print(out/'latest.json')

if __name__=='__main__':main()
