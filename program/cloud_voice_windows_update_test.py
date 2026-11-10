"""Windows-only update/restart/rollback integration on a disposable actual package."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch


def main():
    if os.name!='nt': raise RuntimeError('Windows required')
    root=Path(sys.argv[sys.argv.index('--package-dir')+1]).resolve().parent
    sys.path.insert(0,str(root/'program'))
    import cloud_voice_update as update
    original=update.read_current(root)
    with tempfile.TemporaryDirectory() as td:
        local=Path(td)/'本机数据 with spaces';local.mkdir()
        private=local/'YangNingCloudVoicePreview';private.mkdir()
        env={'LOCALAPPDATA':str(local),'YANGNING_CLOUD_DATA_DIR':str(private)}
        with patch.dict(os.environ,env):
            (private/'user-settings.marker').write_text('preserved')
            personal=root/'program/templates/team.wav';personal.parent.mkdir(exist_ok=True);personal.write_bytes(b'private template')
            version={**original,'version':'0.6-preview.2','update_sequence':9,'source_revision':'b'*40}
            files={name:(root/name).read_bytes() for name in update.MANAGED if (root/name).is_file()}
            files['preview_version.json']=json.dumps(version).encode()
            files['program/cloud_voice_version.py']=b'VERSION="0.6-preview.2"\nUPDATE_SEQUENCE=9\nPRODUCT="YangNing Cloud Voice Independent Preview"\n'
            value={'product':update.PRODUCT,'version':version['version'],'sequence':9,'source_revision':'b'*40,
                   'files':{name:{'content':base64.b64encode(content).decode(),'sha256':update.sha(content)} for name,content in files.items()}}
            data=json.dumps(value).encode()
            descriptor={'product':update.PRODUCT,'schema':1,'version':version['version'],'sequence':9,'source_revision':'b'*40,
                        'payload_url':update.PREFIX+'c'*40+'/cloud_voice_payload.json','payload_size':len(data),'payload_sha256':update.sha(data),'notes':'CI update'}
            plan=update.prepare_update(root,descriptor,lambda url,limit:data,prepare_environment=True)
            # Real Windows PID handle wait.
            child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(.1)'])
            update.wait_process(child.pid)
            launches=[];real_launch=update.launch
            def launch(*args,**kwargs):
                process=real_launch(*args,**kwargs);launches.append(process);return process
            try:
                with patch.object(update,'launch',side_effect=launch),patch.object(update,'wait_process',return_value=None):
                    update.installer(plan,os.getpid())
                assert update.load_plan(plan)['status']=='committed'
                assert update.read_current(root)['version']=='0.6-preview.2'
                assert personal.read_bytes()==b'private template'
                assert (private/'user-settings.marker').read_text()=='preserved'
                assert json.loads((Path(update.load_plan(plan)['tx'])/'boot_ok.json').read_text())['version']=='0.6-preview.2'
                for process in launches:
                    if process.poll() is None: subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
                launches.clear()
                with patch.object(update,'launch',side_effect=launch),patch.object(update,'wait_process',return_value=None):
                    update.installer(plan,os.getpid(),rollback=True)
                assert update.read_current(root)['version']==original['version']
                assert update.load_plan(plan)['status']=='rolled_back'
                assert not (root/'.runtime_selector.json').exists()
                assert personal.read_bytes()==b'private template'
                time.sleep(2)
                assert launches[-1].poll() is None, 'Restored original app should stay running'
            finally:
                for process in launches:
                    if process.poll() is None:subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
    print('Actual Windows side-by-side environment, update, boot acknowledgement and rollback passed; private files preserved.')

if __name__=='__main__':main()
