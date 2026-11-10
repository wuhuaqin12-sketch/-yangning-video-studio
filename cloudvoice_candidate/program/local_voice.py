"""Optional isolated local engine. No torch import or large install in the GUI runtime."""
import atexit
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

from voxcpm_kaggle_worker import REFERENCE_SHA256, PACKAGE_VERSION


def local_root():
    return Path(os.environ.get("YANGNING_CLOUD_DATA_DIR", str(Path.home()/"YangNingCloudVoicePreview"))) / "local_engine"


def python_path():
    return local_root()/"runtime"/("Scripts/python.exe" if os.name=="nt" else "bin/python")


def hardware_report():
    total = available = 0
    if os.name == "nt":
        class Memory(ctypes.Structure):
            _fields_=[("length",ctypes.c_ulong),("load",ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in ("total","available","total_page","available_page","total_virtual","available_virtual","extended")]
        state=Memory();state.length=ctypes.sizeof(state)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
            total,available=state.total,state.available
    elif Path("/proc/meminfo").is_file():
        values={line.split(":")[0]:int(line.split()[1])*1024 for line in Path("/proc/meminfo").read_text().splitlines()}
        total,available=values.get("MemTotal",0),values.get("MemAvailable",0)
    gpus=[]
    try:
        result=subprocess.run(["nvidia-smi","--query-gpu=name,memory.total,memory.free","--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=10,creationflags=0x08000000 if os.name=="nt" else 0)
        if result.returncode==0:
            for line in result.stdout.splitlines():
                name,size,free=line.rsplit(",",2)
                gpus.append({"name":name.strip(),"total_mb":int(size),"free_mb":int(free)})
    except (OSError,ValueError,subprocess.TimeoutExpired): pass
    # Conservative product checks, not promises of model speed or fit.
    suitable=bool(gpus and gpus[0]["total_mb"]>=8192 and total>=16*1024**3)
    return {"total_gb":round(total/1024**3,1),"available_gb":round(available/1024**3,1),"gpus":gpus,
            "recommended":"本机GPU：可先做15秒实测" if suitable else "云端优先；本机CPU速度需实测",
            "local_environment_ready":(local_root()/"ready.json").is_file() and python_path().is_file()}


def describe_hardware(report):
    gpu="；".join(f"{g['name']}，显存{g['total_mb']/1024:.1f}GB，空闲{g['free_mb']/1024:.1f}GB" for g in report["gpus"]) or "未检测到可用的NVIDIA显卡"
    return f"内存 {report['total_gb']}GB，当前可用 {report['available_gb']}GB\n{gpu}\n建议：{report['recommended']}\n本机环境：{'已安装' if report['local_environment_ready'] else '未安装'}。首次请做短试听验证。"


def validate_reference(value):
    path=Path(value or "")
    if not path.is_file() or path.stat().st_size>8*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=REFERENCE_SHA256:
        raise ValueError("请选择已确认的老师原声参考文件，保留原文件内容，不要重新编码。")
    return path.resolve()


def default_reference(data_dir):
    candidates=[Path(data_dir)/"teacher_reference.wav",Path(__file__).parent/"references/teacher_reference.wav",
                Path(data_dir)/"kaggle_voice_jobs/teacher_reference_cache"/(REFERENCE_SHA256+".wav")]
    for path in candidates:
        try: return str(validate_reference(path))
        except ValueError: pass
    return ""


def prepare_environment(emit, runner=subprocess.run):
    root=local_root();root.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(root).free < 14*1024**3:
        raise ValueError("本机模型环境与下载缓存建议至少预留14GB磁盘空间。")
    if sys.version_info[:2] not in ((3,11),(3,12)):
        raise ValueError("本机环境需要64位Python 3.11或3.12。")
    (root/"ready.json").unlink(missing_ok=True)
    def call(args, timeout):
        try:
            runner(args,check=True,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout,
                   creationflags=0x08000000 if os.name=="nt" else 0)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("本机环境准备失败：\n"+(exc.stderr or exc.stdout or str(exc))[-1800:]) from None
    emit(("status","正在安装独立本机环境；首次需要下载较大依赖和模型…"))
    if not python_path().is_file(): call([sys.executable,"-m","venv",str(root/"runtime")],180)
    # Matching PyTorch/torchaudio pair, separate from both Studio and preview environments.
    report=hardware_report()
    index="https://download.pytorch.org/whl/cu126" if report["gpus"] else "https://download.pytorch.org/whl/cpu"
    emit(("status","正在安装本机PyTorch；首次下载较大，请保持联网…"))
    call([str(python_path()),"-m","pip","install","torch==2.6.0","torchaudio==2.6.0","--index-url",index],3600)
    emit(("status","正在安装本机语音克隆依赖…"))
    call([str(python_path()),"-m","pip","install",f"voxcpm=={PACKAGE_VERSION}","soundfile","numpy>=1.26,<3"],3600)
    emit(("status","正在下载并缓存本机模型；以后无需重复下载…"))
    call([str(python_path()),str(Path(__file__).with_name("local_voice_service.py")),"--prepare",str(root/"models")],3600)
    (root/"ready.json").write_text(json.dumps({"voxcpm":PACKAGE_VERSION,"torch":"2.6.0","index":index}),encoding="utf-8")


class LocalEngine:
    def __init__(self, service_path=None):
        self.process=None
        self.lock=threading.Lock()
        self.service_path=Path(service_path) if service_path else Path(__file__).with_name("local_voice_service.py")

    def stop(self):
        process,self.process=self.process,None
        if process and process.poll() is None:
            if not self.lock.locked():
                try:
                    process.stdin.write('{"shutdown":true}\n');process.stdin.flush();process.wait(timeout=3)
                    process.stdin.close();process.stdout.close();return
                except (OSError,ValueError,subprocess.TimeoutExpired): pass
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill();process.wait(timeout=10)
        if process:
            for stream in (process.stdin,process.stdout):
                if stream: stream.close()

    def execute(self, request_file, emit):
        if not self.lock.acquire(blocking=False): raise RuntimeError("本机模型正在处理其他任务。")
        try:
            if not python_path().is_file() or not (local_root()/"ready.json").is_file():
                raise ValueError("请先在更多设置安装本机模型环境。")
            if self.process is None or self.process.poll() is not None:
                env=os.environ.copy();env.update(PYTHONIOENCODING="utf-8",PYTHONUNBUFFERED="1",HF_HUB_DISABLE_SYMLINKS_WARNING="1")
                self.process=subprocess.Popen([str(python_path()),"-u",str(self.service_path),str(local_root()/"models")],
                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace",bufsize=1,env=env,
                    creationflags=0x08000000 if os.name=="nt" else 0)
            process=self.process
            process.stdin.write(json.dumps({"request":str(Path(request_file).resolve())})+"\n");process.stdin.flush()
            from cloud_voice_core import stage_from_log
            log=Path(request_file).with_name("local_engine.log")
            with log.open("w",encoding="utf-8") as output:
                for line in process.stdout:
                    output.write(line);output.flush()
                    if line.startswith("YANGNING_LOCAL="):
                        result=json.loads(line.split("=",1)[1])
                        if result["status"]=="error": raise RuntimeError(result["error"])
                        return result
                    label=stage_from_log(line)
                    if "model_reused" in line: label="已复用本机模型，正在生成…"
                    if label: emit(("status",label.replace("云端","本机")))
            raise RuntimeError("本机模型进程已停止；已完成段落保留，可恢复任务。")
        finally: self.lock.release()


ENGINE=LocalEngine()
atexit.register(ENGINE.stop)


def run_local_job(manifest_path, emit, engine=None):
    from cloud_voice_core import save_json,deliver_result,result_hashes,reuse_completed_result
    from voice_review import write_review
    engine=engine or ENGINE
    path=Path(manifest_path);manifest=json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("execution")!="local": raise ValueError("该记录不是本机生成任务。")
    if manifest["status"]=="completed":
        if result_hashes(manifest["artifacts"])!=manifest.get("result_hashes"): raise ValueError("本机结果已移动或改变，请重新生成。")
        emit(("done",manifest["artifacts"]));return manifest["artifacts"]
    if manifest.get("reuse_from") and manifest["status"]=="prepared":
        reused=reuse_completed_result(path,manifest,emit)
        if reused is not None: return reused
    request_path=path.parent/"request.json";request=json.loads(request_path.read_text(encoding="utf-8"))
    validate_reference(request["reference_path"])
    report=hardware_report()
    required=6 if request.get("local_device")!="cpu" and report["gpus"] else 12
    if report["available_gb"] and report["available_gb"]<required:
        raise ValueError(f"当前可用内存不足{required}GB，请释放其他程序或改用云端。")
    download=path.parent/"download";download.mkdir(exist_ok=True)
    try:
        if manifest.get("edit"):
            from voice_clip_edit import preflight_audio_edit
            preflight_audio_edit(manifest["edit"],path.parent/"edit_source_snapshot")
        checkpoint=download/"checkpoint_manifest.json"
        if checkpoint.is_file():
            from voxcpm_kaggle_worker import checkpoint_parts
            record,parts=checkpoint_parts(checkpoint,request)
            if parts: request.update(resume_checkpoint_job_id=manifest["job_id"],local_checkpoint=str(checkpoint.resolve()),model_revision=record["snapshot_revision"])
        request["output_dir"]=str(download.resolve())
        save_json(request_path,request)
        manifest["status"]="local_running";save_json(path,manifest)
        engine.execute(request_path,emit)
        manifest["artifacts"]=deliver_result(path.parent,manifest)
        if manifest.get("edit"):
            from voice_clip_edit import export_edited_audio
            manifest["artifacts"].update(export_edited_audio(manifest["edit"],manifest["artifacts"]["yangning_final.wav"],manifest["output_dir"],manifest["job_id"]))
        audio=manifest["artifacts"].get("edited_audio",manifest["artifacts"]["yangning_final.wav"])
        review=audio+".review.json";write_review(audio,review);manifest["artifacts"]["audio_review"]=review
        manifest.update(status="completed",cloud_submitted=False,cleanup_status="not_submitted",result_hashes=result_hashes(manifest["artifacts"]))
        manifest.pop("last_error",None);save_json(path,manifest)
        emit(("done",manifest["artifacts"]));return manifest["artifacts"]
    except Exception as exc:
        manifest.update(status="local_failed",last_error=str(exc));save_json(path,manifest)
        raise
