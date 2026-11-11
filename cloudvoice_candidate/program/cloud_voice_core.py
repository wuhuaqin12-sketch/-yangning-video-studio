"""Small desktop-side Kaggle job client; no TTS/model dependency on this PC."""
import json
import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import wave
import tempfile
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

from voxcpm_kaggle_worker import PACKAGE_VERSION, REFERENCE_SHA256, profile_for, split_script, pause_units, natural_pause

_ACTIVE = set()
_ACTIVE_LOCK = threading.Lock()


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(pending, path)


def parse_srt_cues(source):
    """Return cue texts and original timings; reject malformed or overlapping SRT."""
    source = source.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    pattern = re.compile(r"^\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})(?:\s+.*)?$")
    def seconds(value):
        h, m, rest = value.replace(",", ".").split(":")
        sec = float(rest)
        if int(m) >= 60 or sec >= 60: raise ValueError("SRT时间码超出范围")
        return int(h)*3600 + int(m)*60 + sec
    cues=[]
    for block in re.split(r"\n\s*\n", source):
        lines=block.strip().splitlines()
        if not lines: continue
        idx=next((i for i,line in enumerate(lines) if pattern.match(line)),None)
        if idx is None: raise ValueError("SRT包含缺少时间码的段落")
        match=pattern.match(lines[idx]); start,end=seconds(match.group(1)),seconds(match.group(2))
        if end<=start: raise ValueError("SRT结束时间必须晚于开始时间")
        if cues and start<cues[-1]["end"]: raise ValueError("SRT存在重叠时间轴；请先修正")
        content=" ".join(re.sub(r"<[^>]+>","",line).strip() for line in lines[idx+1:]).strip()
        if idx != 1 or not lines[0].strip().isdigit(): raise ValueError("SRT字幕编号缺失或无效")
        if not content: raise ValueError("SRT字幕正文为空")
        cues.append({"index":int(lines[0].strip()),"start":start,"end":end,"text":content})
    if not cues: raise ValueError("SRT没有可朗读的字幕")
    return cues


def script_from_text(text):
    text = text.lstrip("\ufeff").strip()
    timing = re.compile(r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{3}.*$")
    if any(timing.match(line) for line in text.splitlines()):
        cues = []
        for block in re.split(r"\n\s*\n", text):
            lines = block.strip().splitlines()
            mark = next((i for i, line in enumerate(lines) if timing.match(line)), None)
            if mark is None:
                raise ValueError("SRT中存在没有时间码的段落，请先检查格式。")
            spoken = " ".join(re.sub(r"<[^>]+>", "", line).strip() for line in lines[mark + 1:])
            if spoken:
                cues.append(spoken)
        text = " ".join(cues)
    if not text:
        raise ValueError("请输入朗读正文，或导入TXT/SRT。")
    return text


def ensure_teacher_reference(folder, dataset, env, cli, emit):
    """Fetch approved original bytes before paying GPU startup cost; never re-encode."""
    cache = Path(folder).parent / "teacher_reference_cache" / (REFERENCE_SHA256 + ".wav")
    bundled = Path(__file__).parent / "references" / "teacher_reference.wav"
    if bundled.is_file() and hashlib.sha256(bundled.read_bytes()).hexdigest() == REFERENCE_SHA256:
        return bundled.read_bytes()
    if cache.is_file():
        data = cache.read_bytes()
        if hashlib.sha256(data).hexdigest() == REFERENCE_SHA256:
            return data
    emit(("status", "正在校验老师音色…"))
    with tempfile.TemporaryDirectory(prefix="teacher_ref_", dir=folder) as temp:
        cli(["datasets", "download", "-d", dataset, "-p", temp, "--force", "--quiet"], env, timeout=600)
        candidates = []
        for path in Path(temp).rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() == ".zip":
                with zipfile.ZipFile(path) as archive:
                    for member in archive.infolist():
                        if not member.is_dir() and member.filename.lower().endswith(".wav") and 0 < member.file_size <= 8*1024*1024:
                            data = archive.read(member)
                            if hashlib.sha256(data).hexdigest() == REFERENCE_SHA256:
                                candidates.append(data)
            elif path.name.lower().endswith(".wav") and 0 < path.stat().st_size <= 8*1024*1024:
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() == REFERENCE_SHA256:
                    candidates.append(data)
        if not candidates:
            raise ValueError("老师原声校验失败：数据集中没有已确认的原始参考音频。请保留原文件内容；改名或重复.wav扩展名不影响识别。尚未提交云端生成。")
        cache.parent.mkdir(parents=True, exist_ok=True)
        pending = cache.with_name(cache.name + "." + uuid.uuid4().hex + ".tmp")
        pending.write_bytes(candidates[0])
        os.replace(pending, cache)
        return candidates[0]


def build_notebook(request, teacher_reference_bytes=None):
    worker = Path(__file__).with_name("voxcpm_kaggle_worker.py").read_text(encoding="utf-8")
    from punctuation_pause import DEPENDENCIES
    pause_source = Path(__file__).with_name("punctuation_pause.py").read_text(encoding="utf-8")
    install = (
        "import subprocess, sys\nprint('YANGNING_STAGE=dependencies', flush=True)\n"
        f"subprocess.run([sys.executable, '-m', 'pip', 'install', 'torch==2.6.0', 'torchaudio==2.6.0', 'voxcpm=={PACKAGE_VERSION}', 'soundfile', *{DEPENDENCIES!r}], check=True)\n"
    )
    # Ship the same pause implementation to Kaggle, without a sibling-file assumption.
    worker = ("import sys, types\n_pause=types.ModuleType('punctuation_pause')\n"
              "sys.modules['punctuation_pause']=_pause\nexec(" + repr(pause_source) + ",_pause.__dict__)\n" + worker)
    # Data is parsed as JSON, never interpolated into executable Python source.
    setup = "import json\nREQUEST = json.loads(" + repr(json.dumps(request, ensure_ascii=False)) + ")\n"
    if teacher_reference_bytes is not None:
        if hashlib.sha256(teacher_reference_bytes).hexdigest() != REFERENCE_SHA256:
            raise ValueError("老师原声校验失败，不能提交其他音色。")
        # Private job only. Public update packages contain no reference waveform.
        setup += "TEACHER_REFERENCE_B64 = " + repr(base64.b64encode(teacher_reference_bytes).decode("ascii")) + "\n"
    cells = [
        {"cell_type": "markdown", "metadata": {}, "source": [
            "# 私有VoxCPM2生成作业\n", "老师音色；文字语气指令；自然停顿保留；结果待听检。\n"
        ]}
    ]
    guarded_run = (
        "\ntry:\n    run(REQUEST)\n"
        "except Exception as exc:\n"
        "    failed_dir=Path(REQUEST.get('output_dir','/kaggle/working'))\n"
        "    failed_dir.mkdir(parents=True,exist_ok=True)\n"
        "    atomic_json(failed_dir/'job_failure.json', {'job_id':REQUEST['job_id'], 'status':'failed_with_saved_outputs', 'error':str(exc)})\n"
        "    print('YANGNING_STAGE=failed_with_saved_outputs', flush=True)\n"
    )
    for source in (install, setup, worker + guarded_run):
        cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": source.splitlines(True)})
    return {
        "cells": cells, "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
    }


def prepare_job(root, username, dataset, text, language, seed, output_dir, tempo=None, edit=None, prosody_template=None, pronunciation_enabled=True, japanese_readings=None, style_options=None, gain_db=0.0, light_denoise=True, template_mode=None, purpose="full", template_library_dir=None, reuse_completed=False, include_preview=False, execution="cloud", local_reference=None, local_device="auto"):
    if execution not in ("cloud", "local"): raise ValueError("生成模式无效。")
    if execution == "local":
        from local_voice import validate_reference
        local_reference = validate_reference(local_reference)
        if local_device not in ("auto", "cuda", "cpu"): raise ValueError("本机设备选项无效。")
        username, dataset = "local", "local/reference"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", username):
        raise ValueError("请填写Kaggle用户名。")
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+", dataset):
        raise ValueError("私有数据集标识应为：用户名/数据集slug。")
    profile = profile_for(language, tempo)
    from voice_adjust import validate_options
    options = validate_options(profile["tempo"],gain_db,light_denoise,style_options)
    if not str(output_dir).strip():
        raise ValueError("请选择输出目录。")
    srt_cues = parse_srt_cues(text) if re.search(r"\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->", text) else None
    text = "\n".join(cue["text"] for cue in srt_cues) if srt_cues else script_from_text(text)
    requested_seed=int(seed)
    seed = int(seed)
    if not -1 <= seed < 2**31:
        raise ValueError("随机种子须为-1或小于2147483648的非负整数。")
    if seed==-1:
        import secrets
        seed=secrets.randbelow(2**30)
    if purpose not in ("full","preview","terminology"): raise ValueError("任务类型无效。")
    job_id = uuid.uuid4().hex[:12]
    folder = Path(root) / job_id
    folder.mkdir(parents=True)
    target = Path(output_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    request = {
        "timing_schema": 4, "job_id": job_id, "text": text, "language": language, "seed": seed, "requested_seed": requested_seed, "purpose":purpose, "tempo": profile["tempo"],
        "reference_path": f"/kaggle/input/{dataset.split('/')[-1]}/1626_reference.wav",
        "postprocess": {"gain_db": options["gain_db"], "light_denoise": options["denoise"]},
    }
    if execution == "local":
        request.update(execution="local", local_device=local_device, reference_path=str(local_reference))
    if language == "日语" and pronunciation_enabled:
        from japanese_pronunciation import reading_plan
        plan = reading_plan(text, japanese_readings)
        request["reading_text"] = plan.pop("reading_text")
        request["pronunciation"] = plan
        save_json(folder / "pronunciation_plan.json", plan)
        (folder / "reading_text.txt").write_text(request["reading_text"], encoding="utf-8")
    # One utterance for the entire supplied script, regardless of TXT/SRT boundaries.
    request["generation_mode"] = "continuous_full_text"
    request["timing_schema"] = 4
    request["reading_pace_policy"] = "natural_gentle_no_timeline"
    request["punctuation_pause_policy"] = "aligned_punctuation_minimum_v1"
    if srt_cues:
        request["srt_cues"] = srt_cues
        request["srt_timing_policy"] = "source_reference_only"
    if include_preview and purpose == "full" and not edit:
        request["include_preview"] = True  # Extract preview from the one finished waveform.
    request["units"]=[{"text":text,"reading_text":request.get("reading_text",text)}]
    if template_mode is not None:
        from voice_prosody import choose_template
        selection=choose_template(language,template_mode,prosody_template or "",template_root=template_library_dir)
        prosody_template=selection.pop("path")
        request["template_selection"]=selection
    if prosody_template:
        from voice_prosody import analyze_template
        request["prosody_reference"] = analyze_template(prosody_template)
    if style_options:
        from voice_adjust import style_instruction
        request["delivery_instruction"] = style_instruction(style_options)
    save_json(folder / "request.json", request)
    slug = "yangning-voice-" + job_id
    kernel = f"{username}/{slug}"
    save_json(folder / "voxcpm2.ipynb", build_notebook(request))
    save_json(folder / "kernel-metadata.json", {
        "id": kernel, "title": "YangNing Voice " + job_id, "code_file": "voxcpm2.ipynb",
        "language": "python", "kernel_type": "notebook", "is_private": True,
        "enable_gpu": True, "enable_internet": True, "dataset_sources": [dataset],
        "competition_sources": [], "kernel_sources": [], "model_sources": [],
    })
    manifest = {
        "generation_mode": "continuous_full_text",
        "reading_pace_policy": "natural_gentle_no_timeline",
        "punctuation_pause_policy": "aligned_punctuation_minimum_v1",
        "job_id": job_id, "username": username, "dataset": dataset, "kernel": kernel,
        "language": language, "tempo": profile["tempo"], "output_dir": str(target), "status": "prepared",
        "created_utc": datetime.now(timezone.utc).isoformat(), "cleanup_status": "not_requested",
        "postprocess": request["postprocess"], "delivery_instruction": request.get("delivery_instruction", ""),
        "template_selection": request.get("template_selection"), "purpose":purpose,
        "include_preview": request.get("include_preview", False),
        "execution": execution,
    }
    if request.get("pronunciation"):
        manifest["pronunciation"] = request["pronunciation"]
    if edit:
        manifest["edit"] = {**edit, "text": text}
    if reuse_completed and not edit:
        cached = find_completed_result(root, request, manifest)
        if cached:
            manifest["reuse_from"] = str(cached)
    save_json(folder / "manifest.json", manifest)
    # Durable discovery does not depend on a later GUI event being processed.
    save_json(Path(root) / "latest_manifest.json", {"path": str((folder / "manifest.json").resolve())})
    return folder / "manifest.json"


def result_hashes(artifacts):
    from voice_review import file_sha256
    return {name:file_sha256(path) for name,path in artifacts.items() if Path(path).is_file()}


def reusable_result(source, request, manifest):
    from voxcpm_kaggle_worker import request_fingerprint
    source = Path(source)
    old = json.loads(source.read_text(encoding="utf-8"))
    if old.get("status") != "completed" or old.get("edit"):
        return None
    if any(old.get(key) != manifest.get(key) for key in ("username", "dataset", "purpose")):
        return None
    previous = json.loads((source.parent / "request.json").read_text(encoding="utf-8"))
    if request_fingerprint(previous) != request_fingerprint(request):
        return None
    hashes = old.get("result_hashes", {})
    required = ("yangning_final.wav", "yangning_raw.wav", "voice_recipe.json", "script.txt")
    if any(name not in hashes or name not in old.get("artifacts",{}) for name in required):
        return None
    if result_hashes(old["artifacts"]) != hashes:
        return None
    for name in ("yangning_final.wav", "yangning_raw.wav"):
        validate_wav(old["artifacts"][name])
    return old


def find_completed_result(root, request, manifest):
    candidates = sorted(Path(root).glob("*/manifest.json"), key=lambda p:p.stat().st_mtime, reverse=True)[:100]
    for candidate in candidates:
        try:
            if reusable_result(candidate, request, manifest):
                return candidate
        except (OSError, ValueError, KeyError, wave.Error):
            continue  # Missing or edited outputs must never count as a cache hit.
    return None


def reuse_completed_result(manifest_path, manifest, emit):
    """Copy a verified local result under a new version name; no cloud request."""
    source = Path(manifest["reuse_from"])
    request = json.loads((manifest_path.parent / "request.json").read_text(encoding="utf-8"))
    try:
        if source.resolve().parent.parent != manifest_path.resolve().parent.parent:
            return None
        old = reusable_result(source, request, manifest)
    except (OSError, ValueError, KeyError, wave.Error):
        return None
    if old is None:
        return None
    emit(("status", "正文和设置相同，正在复用已校验音频，无需排队…"))
    download = manifest_path.parent / "download"
    download.mkdir(exist_ok=True)
    for name in ("yangning_final.wav", "yangning_raw.wav", "script.txt", "reading_text.txt", "pronunciation_plan.json"):
        if name in old["artifacts"]:
            shutil.copy2(old["artifacts"][name], download / name)
    if "segments" in old["artifacts"]:
        shutil.copy2(old["artifacts"]["segments"], download / "segments.json")
    recipe = json.loads(Path(old["artifacts"]["voice_recipe.json"]).read_text(encoding="utf-8"))
    recipe.update(job_id=manifest["job_id"], reused_from_job_id=old["job_id"], execution="verified_local_reuse")
    save_json(download / "voice_recipe.json", recipe)
    manifest["artifacts"] = deliver_result(manifest_path.parent, manifest)
    from voice_review import write_review
    review = manifest["artifacts"]["yangning_final.wav"] + ".review.json"
    write_review(manifest["artifacts"]["yangning_final.wav"], review)
    manifest["artifacts"]["audio_review"] = review
    manifest.update(status="completed", cleanup_status="not_submitted", cloud_submitted=False,
                    reused_from_job_id=old["job_id"], result_hashes=result_hashes(manifest["artifacts"]))
    save_json(manifest_path, manifest)
    for name in ("voxcpm2.ipynb", "kernel-metadata.json"):
        (manifest_path.parent / name).unlink(missing_ok=True)
    emit(("done", manifest["artifacts"]))
    return manifest["artifacts"]


def redact(message, secret):
    message = str(message)
    if secret:
        message = message.replace(secret, "[REDACTED]")
    return re.sub(r"\b(?:KGAT_|KGRT_)[A-Za-z0-9_.-]+", "[REDACTED]", message)


def auth_env(username, secret, config_dir):
    if not secret.strip():
        raise ValueError("请先保存本人Kaggle访问令牌。")
    env = os.environ.copy()
    for key in ("KAGGLE_KEY", "KAGGLE_USERNAME", "KAGGLE_API_TOKEN", "KAGGLE_TOKEN"):
        env.pop(key, None)
    env["KAGGLE_CONFIG_DIR"] = str(config_dir)
    if secret.strip().upper().startswith(("KGAT_", "KGRT_")):
        env["KAGGLE_API_TOKEN"] = secret.strip()
    else:
        env.update(KAGGLE_USERNAME=username, KAGGLE_KEY=secret.strip())
    return env


def kaggle_cli(args, env, timeout=180):
    binary = Path(sys.executable).with_name("kaggle.exe" if os.name == "nt" else "kaggle")
    executable = str(binary) if binary.is_file() else shutil.which("kaggle")
    if not executable:
        raise RuntimeError("未安装兼容的Kaggle客户端，需要新版工作室及Python3.11或以上。")
    result = subprocess.run([executable, *args], env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    secret = env.get("KAGGLE_API_TOKEN", env.get("KAGGLE_KEY", ""))
    if result.returncode:
        raise RuntimeError(redact((result.stderr or result.stdout)[-2400:], secret))
    return result.stdout.strip()


def state_from_output(output):
    match = re.search(r'has status\s+"([^"]+)"', output, re.I)
    value = match.group(1) if match else output.strip()
    value = value.split(".")[-1].strip().lower()
    if value in {"complete", "completed", "running", "queued", "pending", "error", "failed", "cancelled", "canceled"}:
        return value
    raise RuntimeError("无法识别Kaggle任务状态，保留任务以便恢复。")


def stage_from_log(log):
    # Kaggle may return plain text or a JSON array of stream events.
    text=str(log)
    try:
        events=json.loads(text)
        if isinstance(events,list):
            text="\n".join(str(item.get("data","")) for item in events if isinstance(item,dict))
    except (ValueError,TypeError): pass
    matches=re.findall(r"YANGNING_STAGE=([a-z_]+)",text)
    stages={"dependencies":"云端正在安装依赖…","preflight":"云端正在检查GPU和老师原声参考文件…",
            "model_download":"云端正在下载或载入模型…","generation":"云端正在生成音频…",
            "postprocess":"云端正在执行速度、音量和降噪处理…",
            "punctuation_alignment":"云端正在定位逗号、句号并补入停顿；首次需下载约1.2GB定位模型…"}
    label=stages.get(matches[-1],"") if matches else ""
    counts=re.findall(r"已生成 (\d+)/(\d+) 个完整语义段",text)
    if label and matches[-1]=="generation" and counts:
        label=f"云端已生成 {counts[-1][0]}/{counts[-1][1]} 个完整语义段…"
    return label


def validate_wav(path):
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 48000) or wav.getnframes() <= 0:
            raise ValueError("云端WAV格式不符合48kHz单声道PCM16标准。")


def deliver_result(folder, manifest):
    source = folder / "download"
    recipe = json.loads((source / "voice_recipe.json").read_text(encoding="utf-8"))
    if (recipe.get("status") != "generated_pending_review" or recipe.get("job_id") != manifest["job_id"]
            or recipe.get("reference_sha256") != REFERENCE_SHA256 or recipe.get("language") != manifest["language"]
            or recipe.get("template_audio_used") is not False or recipe.get("silence_trimmed") is not False
            or recipe.get("pitch_ratio") != 1.0 or recipe.get("profile", {}).get("tempo") != manifest.get("tempo", profile_for(manifest["language"])["tempo"])):
        raise ValueError("云端制作记录不完整或与任务不一致，保留云端文件以便检查。")
    if manifest.get("generation_mode")=="continuous_full_text":
        audit=recipe.get("generation_audit",{})
        if (recipe.get("generation_mode")!="continuous_full_text" or audit.get("model_calls") not in (0,1) or audit.get("eos_observed") is not True):
            raise ValueError("云端未确认全文单次生成并正常结束，未交付可能混入逐句生成的结果。")
    if manifest.get("punctuation_pause_policy"):
        from punctuation_pause import POLICY
        report=recipe.get("punctuation_pauses",{})
        if report.get("policy")!=POLICY or manifest["punctuation_pause_policy"]!=POLICY:
            raise ValueError("云端缺少标点停顿修复记录；未将未经补停顿的声音作为新版结果交付。")
    if manifest.get("purpose","full")!="full" and recipe.get("purpose")!=manifest["purpose"]:
        raise ValueError("试听任务类型记录不一致。")
    if manifest.get("pronunciation") and recipe.get("pronunciation") != manifest["pronunciation"]:
        raise ValueError("云端读音校正记录与任务不一致，未将音频标记为完成。")
    if manifest.get("template_selection") and recipe.get("template_selection") != manifest["template_selection"]:
        raise ValueError("自动/手动模板执行记录与任务不一致。")
    if manifest.get("delivery_instruction") and recipe.get("delivery_instruction") != manifest["delivery_instruction"]:
        raise ValueError("语气要求与云端返回记录不一致。")
    if recipe.get("postprocess") is not None and recipe["postprocess"] != manifest.get("postprocess", {"gain_db":0.0,"light_denoise":True}):
        raise ValueError("音量或降噪设置与任务不一致。")
    if (manifest.get("postprocess",{}).get("gain_db",0) != 0 or manifest.get("postprocess",{}).get("light_denoise",True) is not True) and recipe.get("postprocess") is None:
        raise ValueError("缺少自定义音量和降噪的执行记录。")
    target = Path(manifest["output_dir"])
    target.mkdir(parents=True, exist_ok=True)
    prefix = "YangNing_TeacherVoice_" + datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d_%H%M%S_JST_") + manifest["job_id"]
    artifacts = {}
    for name, suffix in (("yangning_final.wav", ".wav"), ("yangning_raw.wav", "_raw.wav"),
                         ("voice_recipe.json", "_recipe.json"), ("script.txt", "_script.txt")):
        src = source / name
        if name.endswith(".wav"):
            validate_wav(src)
        dst = target / (prefix + suffix)
        temporary = dst.with_suffix(dst.suffix + ".partial")
        shutil.copy2(src, temporary)
        os.replace(temporary, dst)
        artifacts[name] = str(dst)
    for name, suffix in (("reading_text.txt", "_reading_text.txt"), ("pronunciation_plan.json", "_pronunciation_plan.json"),
                         ("punctuation_pauses.json", "_punctuation_pauses.json")):
        src = source/name if (source/name).is_file() else folder/name
        if src.is_file():
            dst = target/(prefix+suffix)
            shutil.copy2(src,dst)
            artifacts[name] = str(dst)
    if (source/"segments.json").is_file():
        from voice_workflows import load_segments
        dst=Path(artifacts["yangning_final.wav"]+".segments.json")
        shutil.copy2(source/"segments.json",dst)
        load_segments(artifacts["yangning_final.wav"])
        artifacts["segments"]=str(dst)
        if manifest.get("include_preview") and not manifest.get("edit"):
            from voice_workflows import export_opening_preview
            preview_path=target/(prefix+"_preview.wav")
            export_opening_preview(artifacts["yangning_final.wav"],preview_path)
            artifacts["preview_audio"]=str(preview_path)
    return artifacts


def prepare_resume_job(manifest_path):
    original=Path(manifest_path)
    old=json.loads(original.read_text(encoding="utf-8"))
    if old.get("status")!="remote_failed": raise ValueError("续生成只用于已经失败且保留了断点的作业；运行中的任务请使用恢复最近任务。")
    if not (original.parent/"request.json").is_file() or not (original.parent/"download"/"checkpoint_manifest.json").is_file():
        raise ValueError("这个作业没有平台保留的有效断点，无法续生成。请查看日志修正后重新生成。")
    request=json.loads((original.parent/"request.json").read_text(encoding="utf-8"))
    if request.get("generation_mode") != "continuous_full_text": raise ValueError("旧版逐句断点不能用于全文连续生成，请点击生成音频重新生成全文。")
    from voxcpm_kaggle_worker import checkpoint_parts
    checkpoint,parts=checkpoint_parts(original.parent/"download"/"checkpoint_manifest.json",request)
    if not parts: raise ValueError("这个作业没有可恢复的已完成段落；请查看日志修正错误后重新生成。")
    job_id=uuid.uuid4().hex[:12];folder=original.parent.parent/job_id;folder.mkdir()
    request.update(job_id=job_id,resume_checkpoint_job_id=old["job_id"],model_revision=checkpoint["snapshot_revision"])
    kernel=f"{old['username']}/yangning-voice-{job_id}"
    save_json(folder/"request.json",request)
    save_json(folder/"voxcpm2.ipynb",build_notebook(request))
    save_json(folder/"kernel-metadata.json",{"id":kernel,"title":"YangNing Resume "+job_id,"code_file":"voxcpm2.ipynb",
              "language":"python","kernel_type":"notebook","is_private":True,"enable_gpu":True,"enable_internet":True,
              "dataset_sources":[old["dataset"]],"kernel_sources":[old["kernel"]],"competition_sources":[],"model_sources":[]})
    record={key:value for key,value in old.items() if key in ("username","dataset","language","tempo","output_dir","postprocess","delivery_instruction","template_selection","pronunciation","edit","purpose","include_preview")}
    record.update(job_id=job_id,kernel=kernel,status="prepared",cleanup_status="not_requested",created_utc=datetime.now(timezone.utc).isoformat(),
                  retained_kernels=list(dict.fromkeys(old.get("retained_kernels",[])+[old["kernel"]])),resume_from=str(original))
    save_json(folder/"manifest.json",record)
    save_json(folder.parent/"latest_manifest.json",{"path":str((folder/"manifest.json").resolve())})
    return folder/"manifest.json"


def run_job(manifest_path, secret, emit, cli=kaggle_cli, sleep=time.sleep, timeout_seconds=9*60*60, audio_only=False, cancel_event=None):
    if cancel_event is not None:
        original_cli=cli
        def cancellable_cli(*args,**kwargs):
            if cancel_event.is_set(): raise RuntimeError("已停止等待云端任务；任务身份保留。")
            result=original_cli(*args,**kwargs)
            if cancel_event.is_set(): raise RuntimeError("已停止等待云端任务；任务身份保留。")
            return result
        cli=cancellable_cli
        def cancellable_sleep(seconds):
            if cancel_event.wait(seconds): raise RuntimeError("已停止等待云端任务；任务身份保留。")
        sleep=cancellable_sleep
    manifest_path = Path(manifest_path)
    lock_key = str(manifest_path.resolve())
    with _ACTIVE_LOCK:
        if lock_key in _ACTIVE:
            raise RuntimeError("这个任务正在本机后台处理中，请勿重复提交。")
        _ACTIVE.add(lock_key)
    try:
        return _run_job(manifest_path, secret, emit, cli, sleep, timeout_seconds, audio_only)
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(lock_key)


def _run_job(manifest_path, secret, emit, cli, sleep, timeout_seconds, audio_only=False):
    folder = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("cloud_submitted") is False and manifest["status"] == "completed":
        if result_hashes(manifest["artifacts"]) != manifest.get("result_hashes"):
            raise ValueError("复用的音频已移动或改变，请重新生成；不会自动提交云端任务。")
        emit(("done", manifest["artifacts"]))
        return manifest["artifacts"]
    if manifest["status"] == "prepared" and manifest.get("reuse_from"):
        cached = reuse_completed_result(manifest_path, manifest, emit)
        if cached is not None:
            return cached
    config_dir = folder / "auth_config"
    config_dir.mkdir(exist_ok=True)
    env = auth_env(manifest["username"], secret, config_dir)
    kernel = manifest["kernel"]
    try:
        if manifest["status"] == "prepared":
            if manifest.get("edit", {}).get("kind") == "audio":
                from voice_clip_edit import preflight_audio_edit
                preflight_audio_edit(manifest["edit"], folder / "edit_source_snapshot")
            elif manifest.get("edit") and not audio_only:
                from voice_clip_edit import preflight_edit
                preflight_edit(manifest["edit"], folder / "edit_source_snapshot")
            reference_bytes = ensure_teacher_reference(folder, manifest["dataset"], env, cli, emit)
            request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
            save_json(folder / "voxcpm2.ipynb", build_notebook(request, reference_bytes))
            # Save the identity before submission: a timed-out push may still start remotely.
            manifest["status"] = "submitting"
            save_json(manifest_path, manifest)
            emit(("status", "正在提交私有GPU作业；尚未开始生成…"))
            cli(["kernels", "push", "-p", str(folder)], env, timeout=600)
            manifest["status"] = "submitted"
            save_json(manifest_path, manifest)
        if manifest["status"] == "remote_failed":
            raise RuntimeError("最近的云端任务已失败或取消，恢复不会重复提交。请在更多设置查看日志，修正后点击生成音频提交新任务。")
        if manifest["status"] not in ("audio_ready", "completed"):
            deadline = time.monotonic() + timeout_seconds
            next_log = 0
            last_stage = ""
            while time.monotonic() < deadline:
                state = state_from_output(cli(["kernels", "status", kernel], env, timeout=180))
                if state in {"complete", "completed"}:
                    break
                if state in {"error", "failed", "cancelled", "canceled"}:
                    try:
                        log = cli(["kernels", "logs", kernel], env, timeout=180)
                        (folder / "remote_error.log").write_text(redact(log, secret), encoding="utf-8")
                    except Exception:
                        pass
                    try:
                        download=folder/"download";download.mkdir(exist_ok=True)
                        cli(["kernels","output",kernel,"-p",str(download),"-o"],env,timeout=600)
                        if (download/"checkpoint_manifest.json").is_file():
                            from voxcpm_kaggle_worker import checkpoint_parts
                            request=json.loads((folder/"request.json").read_text(encoding="utf-8"))
                            checkpoint,parts=checkpoint_parts(download/"checkpoint_manifest.json",request)
                            manifest["completed_segments"]=len(parts)
                            manifest["total_segments"]=checkpoint["total"]
                    except Exception as checkpoint_error:
                        manifest["checkpoint_error"]=redact(checkpoint_error,secret)
                    manifest["status"] = "remote_failed"
                    manifest["remote_state"] = state
                    raise RuntimeError(f"云端任务已失败或取消。已保存{manifest.get('completed_segments',0)}个可校验段落；有断点时可在更多设置点击续生成未完成段。没有断点则先查看日志修正错误。")
                manifest["remote_state"] = state
                if state=="running" and time.monotonic() >= next_log:
                    try:
                        log=cli(["kernels","logs",kernel],env,timeout=45)
                        last_stage=stage_from_log(log) or last_stage
                    except Exception: pass  # Status remains authoritative if live logs are unavailable.
                    next_log=time.monotonic()+60
                emit(("status", "正在等待Kaggle分配资源（排队）…" if state in {"queued","pending"} else (last_stage or "云端正在运行：可能在安装依赖、下载模型或生成音频；不是排队。")))
                sleep(10)
            else:
                raise TimeoutError("等待云端超时，任务身份已保存，可稍后恢复，未重复提交。")
            download = folder / "download"
            download.mkdir(exist_ok=True)
            emit(("status", "正在下载WAV和制作记录…"))
            cli(["kernels", "output", kernel, "-p", str(download), "-o"], env, timeout=900)
            if (download/"job_failure.json").is_file():
                failed=json.loads((download/"job_failure.json").read_text(encoding="utf-8"))
                if failed.get("job_id")!=manifest["job_id"]: raise ValueError("云端失败记录与任务不一致。")
                manifest["status"]="remote_failed"
                manifest["completed_segments"]=0
                if (download/"checkpoint_manifest.json").is_file():
                    from voxcpm_kaggle_worker import checkpoint_parts
                    request=json.loads((folder/"request.json").read_text(encoding="utf-8"))
                    checkpoint,parts=checkpoint_parts(download/"checkpoint_manifest.json",request)
                    manifest["completed_segments"]=len(parts);manifest["total_segments"]=checkpoint["total"]
                save_json(manifest_path,manifest)
                (folder/"remote_error.log").write_text(redact(failed.get("error","未知错误"),secret),encoding="utf-8")
                reason = redact(failed.get("error", "未知错误"), secret)
                raise RuntimeError(f"生成中断，已保存{manifest['completed_segments']}段。\n{reason}\n有断点时可点击续生成未完成段。")
            manifest["artifacts"] = deliver_result(folder, manifest)
            manifest["status"] = "audio_ready"
            manifest.pop("last_error", None)
            save_json(manifest_path, manifest)
        if manifest["status"] == "audio_ready":
            if manifest.get("edit", {}).get("kind") == "audio":
                from voice_clip_edit import export_edited_audio
                manifest["artifacts"].update(export_edited_audio(
                    manifest["edit"], manifest["artifacts"]["yangning_final.wav"], manifest["output_dir"],
                    manifest["job_id"], progress=lambda value: emit(("status", value)),
                ))
            elif manifest.get("edit") and not audio_only:
                from voice_clip_edit import export_edited_clip
                manifest["artifacts"].update(export_edited_clip(
                    manifest["edit"], manifest["artifacts"]["yangning_final.wav"], manifest["output_dir"],
                    manifest["job_id"], progress=lambda value: emit(("status", value)),
                ))
            manifest["status"] = "completed"
            manifest.pop("last_error", None)
            save_json(manifest_path, manifest)
        # A previously completed record must not claim success if the user moved
        # or deleted local outputs; retain remote data when it still exists.
        for name in ("yangning_final.wav","yangning_raw.wav"):
            path=manifest.get("artifacts",{}).get(name,"")
            if not path or not Path(path).is_file():
                raise ValueError("已保存的音频文件已移动或删除。请恢复原路径，或在云端任务仍存在时重新下载输出；不会重复提交。")
            validate_wav(path)
        if manifest.get("artifacts",{}).get("edited_audio"):
            validate_wav(manifest["artifacts"]["edited_audio"])
        from voice_review import write_review
        selected=manifest["artifacts"].get("edited_audio",manifest["artifacts"]["yangning_final.wav"])
        report_path=selected+".review.json"
        write_review(selected,report_path)
        manifest["artifacts"]["audio_review"]=report_path
        save_json(manifest_path,manifest)
        # Only delete remotely after local final/raw WAV and audit files are validated.
        if manifest.get("cleanup_status") != "deleted":
            states=manifest.setdefault("kernel_cleanup",{})
            for cleanup_kernel in list(dict.fromkeys([kernel]+manifest.get("retained_kernels",[]))):
                if states.get(cleanup_kernel)=="deleted": continue
                try:
                    cli(["kernels","delete",cleanup_kernel,"--yes"],env,timeout=180)
                    states[cleanup_kernel]="deleted"
                except Exception as exc:
                    states[cleanup_kernel]="pending";manifest["cleanup_error"]=redact(exc,secret)
                    emit(("warning","WAV已保存；部分私有作业清理失败，恢复任务可重试清理。"))
                save_json(manifest_path,manifest)
            manifest["cleanup_status"]="deleted" if all(value=="deleted" for value in states.values()) else "pending"
            save_json(manifest_path,manifest)
        for name in ("voxcpm2.ipynb", "kernel-metadata.json"):
            (folder / name).unlink(missing_ok=True)
        manifest["result_hashes"] = result_hashes(manifest["artifacts"])
        save_json(manifest_path, manifest)
        emit(("done", manifest["artifacts"]))
        return manifest["artifacts"]
    except Exception as exc:
        manifest["last_error"] = redact(exc, secret)
        save_json(manifest_path, manifest)
        raise RuntimeError(manifest["last_error"]) from None
    finally:
        for key in ("KAGGLE_KEY", "KAGGLE_API_TOKEN"):
            env.pop(key, None)

