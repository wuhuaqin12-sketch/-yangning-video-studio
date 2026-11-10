"""Create code-only update payload and, after its commit is known, a pinned channel descriptor."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile
sys.path.insert(0,str(Path(__file__).parent/'program'))
from cloud_voice_update import PRODUCT,MANAGED,PREFIX,validate_descriptor
from build_cloud_voice_preview import build,FILES


def payload(root,revision,destination):
    root,destination=Path(root),Path(destination);destination.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        archive=Path(td)/'preview.zip';build(root,archive,revision)
        with zipfile.ZipFile(archive) as z:
            prefix='YangNing_CloudVoice_Independent_Preview/'
            files={name:z.read(prefix+name) for name in tuple(FILES)+('preview_version.json',) if prefix+name in z.namelist()}
    version=json.loads(files['preview_version.json']);version['prosody_templates_bundled']=[];version['reference_audio_bundled']=False
    files['preview_version.json']=json.dumps(version,ensure_ascii=False,indent=2).encode()
    value={'product':PRODUCT,'sequence':version['update_sequence'],'version':version['version'],'release_version':version['release_version'],'source_revision':revision,
           'files':{name:{'sha256':hashlib.sha256(content).hexdigest(),'content':base64.b64encode(content).decode()} for name,content in sorted(files.items())}}
    data=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    target=destination/'cloud_voice_payload.json';target.write_bytes(data)
    return {'path':str(target),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'files':len(files),'version':version['version']}


def descriptor(payload_path,payload_commit,notes):
    data=Path(payload_path).read_bytes();value=json.loads(data)
    result={key:value[key] for key in ('product','sequence','version','source_revision')}
    result.update(schema=1,payload_url=PREFIX+payload_commit+'/cloud_voice_payload.json',payload_size=len(data),
                  payload_sha256=hashlib.sha256(data).hexdigest(),notes=notes,release_version=value.get('release_version',value['version']))
    return validate_descriptor(result)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--revision',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();print(json.dumps(payload(Path(__file__).parent,args.revision,args.output)))
