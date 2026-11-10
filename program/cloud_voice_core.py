"""Small desktop-side Kaggle job client; no TTS/model dependency on this PC."""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

from voxcpm_kaggle_worker import PACKAGE_VERSION, REFERENCE_SHA256, profile_for, split_script

_ACTIVE = set()
_ACTIVE_LOCK = threading.Lock()


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(pending, path)


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


def build_notebook(request):
    worker = Path(__file__).with_name("voxcpm_kaggle_worker.py").read_text(encoding="utf-8")
    install = (
        "import subprocess, sys\nprint('YANGNING_STAGE=dependencies', flush=True)\n"
        f"subprocess.run([sys.executable, '-m', 'pip', 'install', 'voxcpm=={PACKAGE_VERSION}', 'soundfile'], check=True)\n"
    )
    # Data is parsed as JSON, never interpolated into executable Python source.
    setup = "import json\nREQUEST = json.loads(" + repr(json.dumps(request, ensure_ascii=False)) + ")\n"
    cells = [
        {"cell_type": "markdown", "metadata": {}, "source": [
            "# 私有VoxCPM2生成作业\n", "1626原声音色；文字语气指令；自然停顿保留；结果待听检。\n"
        ]}
    ]
    for source in (install, setup, worker + "\nrun(REQUEST)\n"):
        cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": source.splitlines(True)})
    return {
        "cells": cells, "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
    }


def prepare_job(root, username, dataset, text, language, seed, output_dir, tempo=None, edit=None, prosody_template=None, pronunciation_enabled=True, japanese_readings=None, style_options=None, gain_db=0.0, light_denoise=True):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", username):
        raise ValueError("请填写Kaggle用户名。")
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+", dataset):
        raise ValueError("私有数据集标识应为：用户名/数据集slug。")
    profile = profile_for(language, tempo)
    from voice_adjust import validate_options
    options = validate_options(profile["tempo"],gain_db,light_denoise,style_options)
    if not str(output_dir).strip():
        raise ValueError("请选择输出目录。")
    text = script_from_text(text)
    seed = int(seed)
    if not -1 <= seed < 2**31:
        raise ValueError("随机种子须为-1或小于2147483648的非负整数。")
    job_id = uuid.uuid4().hex[:12]
    folder = Path(root) / job_id
    folder.mkdir(parents=True)
    target = Path(output_dir).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    request = {
        "job_id": job_id, "text": text, "language": language, "seed": seed, "tempo": profile["tempo"],
        "reference_path": f"/kaggle/input/{dataset.split('/')[-1]}/1626_reference.wav",
        "postprocess": {"gain_db": options["gain_db"], "light_denoise": options["denoise"]},
    }
    if language == "日语" and pronunciation_enabled:
        from japanese_pronunciation import reading_plan
        plan = reading_plan(text, japanese_readings)
        request["reading_text"] = plan.pop("reading_text")
        request["pronunciation"] = plan
        save_json(folder / "pronunciation_plan.json", plan)
        (folder / "reading_text.txt").write_text(request["reading_text"], encoding="utf-8")
    split_script(request.get("reading_text",text))  # Reject oversized single sentences before paying GPU startup time.
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
        "job_id": job_id, "username": username, "dataset": dataset, "kernel": kernel,
        "language": language, "tempo": profile["tempo"], "output_dir": str(target), "status": "prepared",
        "created_utc": datetime.now(timezone.utc).isoformat(), "cleanup_status": "not_requested",
        "postprocess": request["postprocess"], "delivery_instruction": request.get("delivery_instruction", ""),
    }
    if request.get("pronunciation"):
        manifest["pronunciation"] = request["pronunciation"]
    if edit:
        manifest["edit"] = {**edit, "text": text}
    save_json(folder / "manifest.json", manifest)
    # Durable discovery does not depend on a later GUI event being processed.
    save_json(Path(root) / "latest_manifest.json", {"path": str((folder / "manifest.json").resolve())})
    return folder / "manifest.json"


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
    stages={"dependencies":"云端正在安装依赖…","preflight":"云端正在检查GPU和1626参考文件…",
            "model_download":"云端正在下载或载入模型…","generation":"云端正在生成音频…",
            "postprocess":"云端正在执行速度、音量和降噪处理…"}
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
    if manifest.get("pronunciation") and recipe.get("pronunciation") != manifest["pronunciation"]:
        raise ValueError("云端读音校正记录与任务不一致，未将音频标记为完成。")
    if manifest.get("delivery_instruction") and recipe.get("delivery_instruction") != manifest["delivery_instruction"]:
        raise ValueError("语气要求与云端返回记录不一致。")
    if recipe.get("postprocess") is not None and recipe["postprocess"] != manifest.get("postprocess", {"gain_db":0.0,"light_denoise":True}):
        raise ValueError("音量或降噪设置与任务不一致。")
    if (manifest.get("postprocess",{}).get("gain_db",0) != 0 or manifest.get("postprocess",{}).get("light_denoise",True) is not True) and recipe.get("postprocess") is None:
        raise ValueError("缺少自定义音量和降噪的执行记录。")
    target = Path(manifest["output_dir"])
    target.mkdir(parents=True, exist_ok=True)
    prefix = "YangNing_VoxCPM2_1626_" + manifest["job_id"]
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
    for name, suffix in (("reading_text.txt", "_reading_text.txt"), ("pronunciation_plan.json", "_pronunciation_plan.json")):
        src = source/name if (source/name).is_file() else folder/name
        if src.is_file():
            dst = target/(prefix+suffix)
            shutil.copy2(src,dst)
            artifacts[name] = str(dst)
    return artifacts


def run_job(manifest_path, secret, emit, cli=kaggle_cli, sleep=time.sleep, timeout_seconds=9*60*60, audio_only=False):
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
                    manifest["status"] = "remote_failed"
                    manifest["remote_state"] = state
                    raise RuntimeError("云端任务已失败或取消，继续等待不会重新运行。任务与可取得的日志已保留；请查看错误详情，修正后再提交新任务。")
                manifest["remote_state"] = state
                if state=="running" and time.monotonic() >= next_log:
                    try:
                        log=cli(["kernels","logs",kernel],env,timeout=45)
                        last_stage=stage_from_log(log) or last_stage
                    except Exception: pass  # Status remains authoritative if live logs are unavailable.
                    next_log=time.monotonic()+60
                emit(("status", "正在等待Kaggle分配资源（排队）…" if state in {"queued","pending"} else (last_stage or "云端正在运行：可能在安装依赖、下载模型或生成音频；不是排队。")))
                sleep(20)
            else:
                raise TimeoutError("等待云端超时，任务身份已保存，可稍后恢复，未重复提交。")
            download = folder / "download"
            download.mkdir(exist_ok=True)
            emit(("status", "正在下载WAV和制作记录…"))
            cli(["kernels", "output", kernel, "-p", str(download), "-o"], env, timeout=900)
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
        # Only delete remotely after local final/raw WAV and audit files are validated.
        if manifest.get("cleanup_status") != "deleted":
            try:
                cli(["kernels", "delete", kernel, "--yes"], env, timeout=180)
                manifest["cleanup_status"] = "deleted"
            except Exception as exc:
                manifest["cleanup_status"] = "pending"
                manifest["cleanup_error"] = redact(exc, secret)
                emit(("warning", "WAV已保存；私有云端任务清理失败，稍后恢复任务可重试清理。"))
            save_json(manifest_path, manifest)
        for name in ("voxcpm2.ipynb", "kernel-metadata.json"):
            (folder / name).unlink(missing_ok=True)
        emit(("done", manifest["artifacts"]))
        return manifest["artifacts"]
    except Exception as exc:
        manifest["last_error"] = redact(exc, secret)
        save_json(manifest_path, manifest)
        raise RuntimeError(manifest["last_error"]) from None
    finally:
        for key in ("KAGGLE_KEY", "KAGGLE_API_TOKEN"):
            env.pop(key, None)

