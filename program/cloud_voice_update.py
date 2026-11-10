"""Independent, pinned-source updater. Uses only stdlib; never handles credentials."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid

PRODUCT="YangNing Cloud Voice Independent Preview"
REPOSITORY="wuhuaqin12-sketch/-yangning-video-studio"
CHANNEL_URL=f"https://raw.githubusercontent.com/{REPOSITORY}/cloud-voice-preview-updates/cloud_voice_update.json"
PREFIX=f"https://raw.githubusercontent.com/{REPOSITORY}/"
MAX_PAYLOAD=4*1024*1024
MANAGED={
    "START_CLOUD_VOICE_PREVIEW.bat","launch_cloud_voice_preview.ps1","preview_requirements.txt",
    "README_CLOUD_PREVIEW.zh-CN.md","KAGGLE_VOXCPM2_SETUP.md","CLOUD_VOICE_EDITING_REQUIREMENTS.md",
    "preview_version.json",
    *["program/"+name for name in (
        "cloud_voice_preview.py","preview_python_check.py","cloud_voice_core.py","kaggle_voice.py",
        "voxcpm_kaggle_worker.py","voice_clip_edit.py","cloud_voice_test.py","voice_workflows.py",
        "voice_review.py","voice_adjust.py","voice_prosody.py","japanese_pronunciation.py",
        "cloud_voice_update.py","cloud_voice_version.py")],
}
REQUIRED={"START_CLOUD_VOICE_PREVIEW.bat","launch_cloud_voice_preview.ps1","preview_requirements.txt",
          "preview_version.json","program/cloud_voice_update.py","program/cloud_voice_version.py",
          "program/cloud_voice_preview.py","program/kaggle_voice.py"}


def allowed_file(name):
    return isinstance(name,str) and (name in MANAGED or re.fullmatch(r"program/[a-z][a-z0-9_]*\.py",name) is not None)


def data_root():
    return Path(os.environ.get("YANGNING_CLOUD_DATA_DIR",str(Path(os.environ.get("LOCALAPPDATA",str(Path.home())))/"YangNingCloudVoicePreview")))


def replace_file(source,target):
    for attempt in range(20):
        try: os.replace(source,target);return
        except PermissionError:
            if attempt==19: raise
            time.sleep(.15)


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    pending=path.with_suffix(path.suffix+".tmp")
    pending.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8");replace_file(pending,path)


def sha(data): return hashlib.sha256(data).hexdigest()


def read_current(root):
    value=json.loads((Path(root)/"preview_version.json").read_text(encoding="utf-8"))
    if value.get("name")!=PRODUCT or value.get("formal_studio_release") is not False:
        raise ValueError("更新目录不是独立语音工具，已停止。")
    return value


def fetch_bytes(url,limit):
    if not url.startswith(PREFIX): raise ValueError("更新来源不在指定仓库。")
    request=urllib.request.Request(url,headers={"User-Agent":"YangNingCloudVoiceUpdater/1","Cache-Control":"no-cache"})
    with urllib.request.urlopen(request,timeout=40) as response:
        # Raw GitHub content must not redirect to another service.
        if not response.geturl().startswith(PREFIX): raise ValueError("更新地址跳转到未授权来源。")
        if int(response.headers.get("Content-Length",0))>limit: raise ValueError("更新文件过大。")
        result=response.read(limit+1)
    if len(result)>limit: raise ValueError("更新文件超过大小限制。")
    return result


def validate_descriptor(value):
    if value.get("product")!=PRODUCT or value.get("schema")!=1: raise ValueError("更新产品或协议不匹配。")
    if type(value.get("sequence")) is not int or not 1<=value["sequence"]<10**9: raise ValueError("更新版本序号无效。")
    if not re.fullmatch(r"\d+\.\d+-preview\.\d+",value.get("version","")): raise ValueError("更新版本号无效。")
    if not re.fullmatch(r"[0-9a-f]{40}",value.get("source_revision","")): raise ValueError("缺少源码版本记录。")
    expected=re.escape(PREFIX)+r"[0-9a-f]{40}/cloud_voice_payload\.json"
    if not re.fullmatch(expected,value.get("payload_url","")): raise ValueError("更新包必须固定到指定仓库的完整提交版本。")
    if not re.fullmatch(r"[0-9a-f]{64}",value.get("payload_sha256","")): raise ValueError("更新包校验值无效。")
    if type(value.get("payload_size")) is not int or not 0<value["payload_size"]<=MAX_PAYLOAD: raise ValueError("更新包大小无效。")
    if not isinstance(value.get("notes",""),str) or len(value.get("notes",""))>10000: raise ValueError("更新说明无效。")
    return value


def check_update(root,fetcher=fetch_bytes):
    current=read_current(root)
    candidate=validate_descriptor(json.loads(fetcher(CHANNEL_URL,65536)))
    sequence=int(current.get("update_sequence",0))
    if candidate["sequence"]==sequence and candidate["version"]!=current.get("version"):
        raise ValueError("更新渠道版本记录冲突，请稍后重试。")
    return {"available":candidate["sequence"]>sequence,"current":current.get("version","未知"),"update":candidate}


def validate_payload(data,descriptor):
    validate_descriptor(descriptor)
    if len(data)!=descriptor["payload_size"] or sha(data)!=descriptor["payload_sha256"]: raise ValueError("下载校验失败，原版本未更改。")
    value=json.loads(data)
    if any(value.get(key)!=descriptor.get(key) for key in ("product","sequence","version","source_revision")):
        raise ValueError("更新包内容与版本说明不一致。")
    files=value.get("files")
    if not isinstance(files,dict) or not REQUIRED.issubset(files) or not all(allowed_file(name) for name in files):
        raise ValueError("更新文件清单不完整或包含用户数据目录。")
    decoded={}
    for name,record in files.items():
        if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or "\\" in name or ":" in name:
            raise ValueError("更新文件路径无效。")
        content=base64.b64decode(record["content"],validate=True)
        if sha(content)!=record.get("sha256"): raise ValueError("更新文件损坏："+name)
        if name.endswith(".py"): compile(content.decode("utf-8"),name,"exec")
        decoded[name]=content
    version=json.loads(decoded["preview_version.json"])
    if version.get("name")!=PRODUCT or version.get("formal_studio_release") is not False or version.get("version")!=descriptor["version"] or version.get("update_sequence")!=descriptor["sequence"] or version.get("source_revision")!=descriptor["source_revision"]:
        raise ValueError("更新包版本标识无效。")
    return decoded


def safe_target(root,name):
    root=Path(root).resolve();target=root/name
    if target.is_symlink() or root not in target.resolve().parents: raise ValueError("更新目标包含外部链接。")
    parent=target.parent
    while parent!=root:
        if parent.is_symlink(): raise ValueError("更新目标目录包含外部链接。")
        parent=parent.parent
    return target


def prepare_update(root,descriptor,fetcher=fetch_bytes,prepare_environment=True):
    root=Path(root).resolve();current=read_current(root)
    if descriptor["sequence"]<=int(current.get("update_sequence",0)): raise ValueError("不安装旧版或相同版本。")
    decoded=validate_payload(fetcher(descriptor["payload_url"],MAX_PAYLOAD),descriptor)
    tx=data_root()/"updates"/uuid.uuid4().hex;stage=tx/"stage";stage.mkdir(parents=True)
    for name,content in decoded.items():
        target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
    runtime=data_root()/"runtimes"/tx.name
    if prepare_environment:
        if os.name!="nt": raise RuntimeError("自动安装目前用于Windows版本。")
        with (tx/"setup.log").open("wb") as log:
            result=subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(stage/"launch_cloud_voice_preview.ps1"),"-SetupOnly","-RuntimeDir",str(runtime)],stdout=log,stderr=subprocess.STDOUT,timeout=1200)
        if result.returncode: raise RuntimeError("新版依赖准备失败，原版本未更改。请查看更新检查窗口的日志路径："+str(tx/"setup.log"))
    plan={"schema":1,"root":str(root),"tx":str(tx.resolve()),"stage":str(stage.resolve()),"runtime":str(runtime.resolve()),
          "files":{name:sha(content) for name,content in decoded.items()},"from_version":current.get("version"),
          "to_version":descriptor["version"],"sequence":descriptor["sequence"],"status":"prepared"}
    atomic_json(tx/"plan.json",plan)
    # The helper must run from outside the installation so it can replace itself.
    shutil.copy2(Path(__file__),tx/"worker.py")
    return tx/"plan.json"


def load_plan(path):
    path=Path(path).resolve();plan=json.loads(path.read_text(encoding="utf-8"))
    tx=Path(plan["tx"]).resolve()
    if path!=tx/"plan.json" or path.parent.parent.resolve()!=(data_root()/"updates").resolve() or plan.get("schema")!=1:
        raise ValueError("更新事务目录无效。")
    if Path(plan["stage"]).resolve()!=tx/"stage" or not REQUIRED.issubset(plan["files"]) or not all(allowed_file(name) for name in plan["files"]):
        raise ValueError("更新事务清单无效。")
    for name in plan["files"]: safe_target(Path(plan["root"]),name)
    return plan


def restore(plan_path):
    plan=load_plan(plan_path);root=Path(plan["root"]);tx=Path(plan["tx"])
    entries=json.loads((tx/"backup.json").read_text(encoding="utf-8"))
    for name,expected in entries.items():
        if not allowed_file(name) and name not in {"FILES_SHA256.json",".runtime_selector.json"}: raise ValueError("备份路径无效。")
        if expected is not None and sha((tx/"backup"/name).read_bytes())!=expected: raise ValueError("备份校验失败，尚未开始恢复。")
    for name,expected in entries.items():
        target=safe_target(root,name)
        if expected is None:
            target.unlink(missing_ok=True)
        else:
            source=tx/"backup"/name
            if sha(source.read_bytes())!=expected: raise ValueError("备份校验失败，停止恢复："+name)
            target.parent.mkdir(parents=True,exist_ok=True)
            pending=target.with_name(target.name+".restore_tmp");shutil.copy2(source,pending);replace_file(pending,target)
    plan["status"]="rolled_back";atomic_json(plan_path,plan)


def apply_plan(plan_path,fault=None,health_check=True):
    plan=load_plan(plan_path);root=Path(plan["root"]);tx=Path(plan["tx"])
    if read_current(root).get("version")!=plan["from_version"]: raise ValueError("准备更新后程序版本发生变化，请重新检查。")
    if plan["status"]!="prepared": raise ValueError("更新事务已处理，不能重复安装。")
    for name,expected in plan["files"].items():
        if sha((tx/"stage"/name).read_bytes())!=expected: raise ValueError("待安装文件发生变化。")
    entries={}
    names=list(plan["files"])+["FILES_SHA256.json",".runtime_selector.json"]
    for name in names:
        target=safe_target(root,name)
        if target.exists():
            if not target.is_file(): raise ValueError("更新目标不是文件："+name)
            backup=tx/"backup"/name;backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,backup)
            entries[name]=sha(backup.read_bytes())
        else: entries[name]=None
    atomic_json(tx/"backup.json",entries)
    plan["status"]="applying";atomic_json(plan_path,plan)
    try:
        for name in plan["files"]:
            target=safe_target(root,name);target.parent.mkdir(parents=True,exist_ok=True)
            pending=target.with_name(target.name+".update_tmp");shutil.copy2(tx/"stage"/name,pending);replace_file(pending,target)
            if fault: fault(name)
        atomic_json(root/".runtime_selector.json",{"runtime":plan["runtime"]})
        atomic_json(root/"FILES_SHA256.json",plan["files"])
        if health_check:
            python=Path(plan["runtime"])/"Scripts"/"python.exe"
            result=subprocess.run([str(python),str(root/"program"/"cloud_voice_preview.py"),"--health-check"],capture_output=True,timeout=90)
            if result.returncode: raise RuntimeError("新版启动检查失败。")
        plan["status"]="awaiting_boot";atomic_json(plan_path,plan)
    except Exception:
        restore(plan_path)
        raise


def acknowledge_boot(root):
    record=os.environ.get("YANGNING_UPDATE_PLAN","")
    if not record: return
    plan=load_plan(record)
    if Path(plan["root"]).resolve()!=Path(root).resolve() or plan["status"]!="awaiting_boot": return
    atomic_json(Path(plan["tx"])/"boot_ok.json",{"version":read_current(root)["version"]})


def wait_process(pid):
    if os.name=="nt":
        import ctypes
        kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        kernel.OpenProcess.argtypes=(ctypes.c_ulong,ctypes.c_bool,ctypes.c_ulong);kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes=(ctypes.c_void_p,ctypes.c_ulong);kernel.WaitForSingleObject.restype=ctypes.c_ulong
        kernel.CloseHandle.argtypes=(ctypes.c_void_p,)
        handle=kernel.OpenProcess(0x00100000,False,pid)
        if handle:
            try:
                if kernel.WaitForSingleObject(handle,60000)==0x102: raise RuntimeError("旧程序未退出，未执行更新。")
            finally: kernel.CloseHandle(handle)
    else:
        for _ in range(600):
            try: os.kill(pid,0)
            except ProcessLookupError: return
            time.sleep(.1)
        raise RuntimeError("旧程序未退出。")


def launch(root,plan_path=None):
    env=os.environ.copy()
    env.pop("YANGNING_UPDATE_PLAN",None)
    if plan_path: env["YANGNING_UPDATE_PLAN"]=str(plan_path)
    return subprocess.Popen(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(Path(root)/"launch_cloud_voice_preview.ps1")],cwd=str(root),env=env)


def installer(plan_path,pid,rollback=False):
    plan=load_plan(plan_path);wait_process(pid)
    if rollback:
        restore(plan_path);launch(plan["root"]);return
    try:
        apply_plan(plan_path)
        process=launch(plan["root"],plan_path)
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            ack=Path(plan["tx"])/"boot_ok.json"
            if ack.is_file() and json.loads(ack.read_text()).get("version")==plan["to_version"]:
                plan=load_plan(plan_path);plan["status"]="committed";atomic_json(plan_path,plan)
                atomic_json(data_root()/"updates"/"last_successful.json",{"plan":str(plan_path)})
                return
            if process.poll() is not None: break
            time.sleep(.2)
        if process.poll() is None:
            subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],capture_output=True)
        raise RuntimeError("新版没有完成启动确认，已恢复旧版。")
    except Exception as exc:
        current=load_plan(plan_path)
        if current.get("status") in ("applying","awaiting_boot") and (Path(plan["tx"])/"backup.json").is_file(): restore(plan_path)
        atomic_json(Path(plan["tx"])/"failure.json",{"error":str(exc)})
        atomic_json(data_root()/"updates"/"last_failure.json",{"plan":str(plan_path),"error":str(exc)})
        launch(plan["root"])


def start_installer(plan_path,rollback=False):
    plan=load_plan(plan_path)
    args=[sys.executable,str(Path(plan["tx"])/"worker.py"),"--plan",str(plan_path),"--pid",str(os.getpid())]
    if rollback: args.append("--rollback")
    subprocess.Popen(args,cwd=plan["tx"],creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--plan",required=True);parser.add_argument("--pid",type=int,required=True);parser.add_argument("--rollback",action="store_true")
    args=parser.parse_args();installer(Path(args.plan),args.pid,args.rollback)


def open_update_window(app,install_root=None):
    import tkinter as tk
    from tkinter import ttk,messagebox
    import queue
    import threading
    root=Path(install_root or Path(__file__).resolve().parent.parent)
    previous=getattr(app,"_cloud_update_window",None)
    if previous is not None:
        try:
            if previous.winfo_exists(): previous.lift();return
        except tk.TclError: pass
    window=tk.Toplevel(app.root);app._cloud_update_window=window
    window.title("语音工具 · 检查更新");window.geometry("680x440")
    window.minsize(560,360)
    body=ttk.Frame(window,padding=16);body.pack(fill="both",expand=True)
    def wrap(event):
        for child in body.winfo_children():
            if isinstance(child,ttk.Label) and int(child.cget("wraplength"))>0: child.configure(wraplength=max(350,event.width-32))
    body.bind("<Configure>",wrap)
    state=tk.StringVar(value="正在检查语音工具更新…")
    ttk.Label(body,text="语音工具更新",font=("Microsoft YaHei UI",14,"bold")).pack(anchor="w")
    ttk.Label(body,textvariable=state,wraplength=610).pack(fill="x",pady=10)
    notes=tk.Text(body,height=7,wrap="word",state="disabled");notes.pack(fill="both",expand=True,pady=6)
    ttk.Label(body,text="保留连接信息、老师音色配置、语气模板和历史音频。下载校验后才安装，失败恢复旧版。",wraplength=610).pack(fill="x",pady=7)
    events=queue.Queue();candidate=None;busy=False
    bar=ttk.Progressbar(body,mode="indeterminate");bar.pack(fill="x",pady=5)
    row=ttk.Frame(body);row.pack(fill="x",pady=8)
    def check():
        nonlocal busy
        if busy:return
        busy=True;bar.start(12);check_button.state(["disabled"]);install_button.state(["disabled"])
        state.set("正在检查更新…")
        def work():
            try: events.put(("checked",check_update(root)))
            except Exception as exc: events.put(("error",str(exc)))
        threading.Thread(target=work,daemon=True).start()
    def install():
        nonlocal busy
        if busy or candidate is None:return
        if getattr(app,"_cloud_voice_busy",False):
            messagebox.showinfo("任务正在运行","请等待音频生成、微调或模板处理结束后再更新。",parent=window);return
        busy=True;app._cloud_update_busy=True;bar.start(12)
        install_button.state(["disabled"]);check_button.state(["disabled"]);rollback_button.state(["disabled"])
        state.set("正在下载、校验并准备独立依赖；原版本保持可用，请稍候…")
        def work():
            try: events.put(("ready",str(prepare_update(root,candidate))))
            except Exception as exc:events.put(("error",str(exc)))
        threading.Thread(target=work,daemon=True).start()
    def rollback():
        if busy or getattr(app,"_cloud_voice_busy",False):
            messagebox.showinfo("请稍候","正在处理任务时不能恢复版本。",parent=window);return
        try:
            marker=data_root()/"updates"/"last_successful.json"
            if not marker.is_file(): raise ValueError("尚未通过此功能完成过更新，暂无上一版本备份。")
            record=Path(json.loads(marker.read_text())["plan"]);plan=load_plan(record)
            if Path(plan["root"]).resolve()!=root.resolve() or plan["status"]!="committed" or read_current(root)["version"]!=plan["to_version"]:
                raise ValueError("当前版本没有对应的可恢复备份。")
            start_installer(record,rollback=True);app.root.destroy()
        except Exception as exc:messagebox.showerror("无法恢复",str(exc),parent=window)
    check_button=ttk.Button(row,text="重新检查",command=check);check_button.pack(side="left")
    rollback_button=ttk.Button(row,text="恢复上一版本",command=rollback);rollback_button.pack(side="left",padx=8)
    install_button=ttk.Button(row,text="更新并重启",command=install,state="disabled");install_button.pack(side="right")
    def poll():
        nonlocal busy,candidate
        try:
            while True:
                kind,payload=events.get_nowait()
                busy=False;bar.stop();check_button.state(["!disabled"]);rollback_button.state(["!disabled"])
                if kind=="checked":
                    value=payload["update"];candidate=value if payload["available"] else None
                    state.set(f"当前：{payload['current']}；发现新版：{value['version']}" if candidate else f"已是当前渠道最新版：{payload['current']}")
                    notes.configure(state="normal");notes.delete("1.0","end");notes.insert("1.0",value.get("notes","") or "暂无更新说明。");notes.configure(state="disabled")
                    if candidate: install_button.state(["!disabled"])
                elif kind=="ready":
                    if getattr(app,"_cloud_voice_busy",False):
                        app._cloud_update_busy=False;state.set("更新已准备好，请等待音频任务结束后再点击更新。")
                        install_button.state(["!disabled"]);continue
                    state.set("校验完成，即将安装并重启…")
                    start_installer(Path(payload));app.root.destroy();return
                else:
                    app._cloud_update_busy=False;state.set("检查或下载未完成，原版本未更改："+payload)
                    if candidate:install_button.state(["!disabled"])
        except queue.Empty:pass
        if window.winfo_exists():window.after(150,poll)
    def close():
        if busy:
            messagebox.showinfo("正在处理更新","请等待当前检查或下载结束，避免中断更新准备。",parent=window);return
        window.destroy()
    window.protocol("WM_DELETE_WINDOW",close)
    window.after(100,check);window.after(150,poll)
