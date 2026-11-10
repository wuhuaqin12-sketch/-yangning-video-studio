"""Run the real previous updater's installer against a stable payload on Windows."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch


def main():
    if os.name!="nt": raise RuntimeError("Windows only")
    package=Path(sys.argv[sys.argv.index("--package-dir")+1]).resolve().parent
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    sys.path.insert(0,str(package/"program"))
    import legacy_cloud_voice_update_fixture as legacy
    from build_cloud_voice_preview import FILES
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)/"旧版语音工具 with spaces";root.mkdir()
        names=tuple(FILES)+("preview_version.json",)
        stable={name:(package/name).read_bytes() for name in names}
        for name,data in stable.items():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        meta=json.loads(stable["preview_version.json"])
        old={**meta,"version":"0.6-preview.1","update_sequence":8,"release_version":"0.6-preview.1"}
        legacy.atomic_json(root/"preview_version.json",old)
        (root/"program/cloud_voice_update.py").write_bytes(Path(legacy.__file__).read_bytes())
        (root/"program/cloud_voice_version.py").write_text('VERSION="0.6-preview.1"\nUPDATE_SEQUENCE=8\nPRODUCT="YangNing Cloud Voice Independent Preview"\n')
        personal=root/"program/templates/personal.wav";personal.parent.mkdir(exist_ok=True);personal.write_bytes(b"preserve template")
        private=Path(td)/"用户记录";private.mkdir();(private/"local_engine/models").mkdir(parents=True)
        (private/"local_engine/models/weights.marker").write_bytes(b"preserve cached model")
        (private/"kaggle_voice_settings.json").write_text('{}')
        value={"product":legacy.PRODUCT,"version":meta["version"],"sequence":meta["update_sequence"],"source_revision":meta["source_revision"],
            "files":{name:{"content":base64.b64encode(data).decode(),"sha256":legacy.sha(data)} for name,data in stable.items()}}
        data=json.dumps(value).encode()
        desc={key:value[key] for key in ("product","version","sequence","source_revision")}
        desc.update(schema=1,payload_url=legacy.PREFIX+"c"*40+"/cloud_voice_payload.json",payload_size=len(data),payload_sha256=legacy.sha(data))
        with patch.dict(os.environ,{"YANGNING_CLOUD_DATA_DIR":str(private),"LOCALAPPDATA":str(Path(td)/"localdata")}):
            plan=legacy.prepare_update(root,desc,lambda url,limit:data,prepare_environment=True)
            real_launch=legacy.launch;launches=[]
            def launch(*a,**k):
                process=real_launch(*a,**k);launches.append(process);return process
            try:
                with patch.object(legacy,"wait_process",return_value=None),patch.object(legacy,"launch",side_effect=launch): legacy.installer(plan,os.getpid())
                assert legacy.load_plan(plan)["status"]=="committed", "Legacy installer did not receive stable boot acknowledgement"
                assert legacy.read_current(root)["release_version"]=="0.7.0"
                assert personal.read_bytes()==b"preserve template"
                assert (private/"local_engine/models/weights.marker").read_bytes()==b"preserve cached model"
                for p in launches:
                    if p.poll() is None: subprocess.run(["taskkill","/PID",str(p.pid),"/T","/F"],capture_output=True)
                legacy.restore(plan)
                assert legacy.read_current(root)["version"]=="0.6-preview.1"
            finally:
                for p in launches:
                    if p.poll() is None: subprocess.run(["taskkill","/PID",str(p.pid),"/T","/F"],capture_output=True)
    print("LEGACY_0_6_TO_STABLE_0_7_WINDOWS_UPDATE_OK")


if __name__=="__main__":main()
