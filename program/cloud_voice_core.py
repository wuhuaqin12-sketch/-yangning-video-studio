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

from voxcpm_kaggle_worker import PACKAGE_VERSION, REFERENCE_SHA256, profile_for

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
        "import subprocess, sys\n"
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


def prepare_job(root, username, dataset, text, language, seed, output_dir, tempo=None, edit=None):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", username):
        raise ValueError("请填写Kaggle用户名。")
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+", dataset):
        raise ValueError("私有数据集标识应为：用户名/数据集slug。")
    profile = profile_for(language, tempo)
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
    }
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
    }
    if edit:
        manifest["edit"] = {**edit, "text": text}
    save_json(folder / "manifest.json", manifest)
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
    return artifacts


def run_job(manifest_path, secret, emit, cli=kaggle_cli, sleep=time.sleep, timeout_seconds=9*60*60):
    manifest_path = Path(manifest_path)
    lock_key = str(manifest_path.resolve())
    with _ACTIVE_LOCK:
        if lock_key in _ACTIVE:
            raise RuntimeError("这个任务正在本机后台处理中，请勿重复提交。")
        _ACTIVE.add(lock_key)
    try:
        return _run_job(manifest_path, secret, emit, cli, sleep, timeout_seconds)
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(lock_key)


def _run_job(manifest_path, secret, emit, cli, sleep, timeout_seconds):
    folder = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config_dir = folder / "auth_config"
    config_dir.mkdir(exist_ok=True)
    env = auth_env(manifest["username"], secret, config_dir)
    kernel = manifest["kernel"]
    try:
        if manifest["status"] == "prepared":
            if manifest.get("edit"):
                from voice_clip_edit import preflight_edit
                preflight_edit(manifest["edit"])
            # Save the identity before submission: a timed-out push may still start remotely.
            manifest["status"] = "submitting"
            save_json(manifest_path, manifest)
            emit(("status", "正在提交私有GPU作业…"))
            cli(["kernels", "push", "-p", str(folder)], env, timeout=600)
            manifest["status"] = "submitted"
            save_json(manifest_path, manifest)
        if manifest["status"] not in ("audio_ready", "completed"):
            deadline = time.monotonic() + timeout_seconds
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
                    raise RuntimeError("云端执行失败；任务和日志已保留，可恢复下载或查看Kaggle运行日志。")
                emit(("status", "云端正在排队或生成，可关闭窗口，之后恢复任务。"))
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
            if manifest.get("edit"):
                from voice_clip_edit import export_edited_clip
                manifest["artifacts"].update(export_edited_clip(
                    manifest["edit"], manifest["artifacts"]["yangning_final.wav"], manifest["output_dir"],
                    manifest["job_id"], progress=lambda value: emit(("status", value)),
                ))
            manifest["status"] = "completed"
            manifest.pop("last_error", None)
            save_json(manifest_path, manifest)
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

