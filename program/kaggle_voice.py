import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "YangNingStudio"
SETTINGS = DATA / "kaggle_voice_settings.json"
KEYRING_SERVICE = "YangNingStudio-Kaggle"


def _load_settings():
    try:
        value = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_settings(value):
    DATA.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _kaggle_cli():
    exe = Path(sys.executable).with_name("kaggle.exe" if os.name == "nt" else "kaggle")
    if exe.is_file():
        return str(exe)
    found = shutil.which("kaggle")
    if found:
        return found
    raise RuntimeError("缺少 Kaggle API 命令。此功能需要在新版本工作室中安装 kaggle 依赖。")


def _run_cli(args, env, cwd=None, timeout=180):
    result = subprocess.run(
        [_kaggle_cli(), *args],
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        details = (result.stderr or result.stdout or "Kaggle API 调用失败").strip()
        raise RuntimeError(details[-1800:])
    return result.stdout.strip()


def _build_notebook(text, seed, reference_dataset, job_id, language):
    dataset_name = reference_dataset.rsplit("/", 1)[-1]
    reference_path = f"/kaggle/input/{dataset_name}/1626_reference.wav"
    output_name = f"yangning_1626_{job_id}.wav"
    style_guides = {\n        "日语": "(Warm, gentle Japanese narration, effortless and relaxed delivery, smoothly connected phrases, subtle intonation)",\n        "英语": "(Calm, natural English narration, warm and gentle, smoothly connected phrases, moderate pace, subtle intonation and natural pauses)",\n        "法语": "(Natural French narration, calm and flowing, gentle emphasis, moderate pace, subtle intonation and natural pauses)",\n        "德语": "(Natural German narration, calm and flowing, gentle emphasis, moderate pace, subtle intonation and natural pauses)",\n        "印尼语": "(Natural Indonesian narration, calm and flowing, gentle emphasis, moderate pace, subtle intonation and natural pauses)",\n        "粤语/中文": "(Natural Cantonese or Chinese narration, calm and flowing, gentle emphasis, moderate pace, subtle intonation and natural pauses)",\n    }\n    style_instruction = style_guides.get(language, style_guides["日语"])\n    code = f"""!pip -q install voxcpm==2.0.3 soundfile

from pathlib import Path
import numpy as np
import soundfile as sf
from voxcpm import VoxCPM

TEXT = {json.dumps(style_instruction + text, ensure_ascii=False)}
REFERENCE = Path({json.dumps(reference_path)})
OUTPUT = Path('/kaggle/working/{output_name}')

if not REFERENCE.is_file():
    raise FileNotFoundError(f'私有参考音频未找到：{{REFERENCE}}')

model = VoxCPM.from_pretrained('openbmb/VoxCPM2', device='cuda')
audio = model.generate(
    text=TEXT,
    reference_wav_path=str(REFERENCE),
    prompt_wav_path=None,
    prompt_text=None,
    cfg_value=2.0,
    inference_timesteps=10,
    normalize=False,
    denoise=False,
    retry_badcase=False,
    seed={int(seed) if int(seed) >= 0 else 'None'},
)
audio = np.asarray(audio, dtype=np.float32).reshape(-1)
sf.write(OUTPUT, audio, model.tts_model.sample_rate, subtype='PCM_16')
print(f'WAV={OUTPUT}')
"""
    return {
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": [
                "# 杨宁老师 VoxCPM2 私有语音任务\n",
                "私有 Kaggle Notebook；只以 1626 老师原声作为音色参考。模板音频不会传入，所选语言会加入语气文字指令。\n",
            ]},
            {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": code.splitlines(True)},
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _job_files(folder, username, dataset, text, seed, job_id, language):
    slug = f"yangning-voice-{job_id}"
    kernel_ref = f"{username}/{slug}"
    (folder / "voxcpm2.ipynb").write_text(
        json.dumps(_build_notebook(text, seed, dataset, job_id, language), ensure_ascii=False),
        encoding="utf-8",
    )
    metadata = {
        "id": kernel_ref,
        "title": f"YangNing VoxCPM2 {job_id}",
        "code_file": "voxcpm2.ipynb",
        "language": "python",
        "kernel_type": "notebook",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": True,
        "dataset_sources": [dataset],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
    }
    (folder / "kernel-metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return kernel_ref, slug


def open_kaggle_voice(app, parent=None):
    settings = _load_settings()
    win = tk.Toplevel(parent or app.root)
    win.title("免费 Kaggle GPU · VoxCPM2 云端克隆")
    win.geometry("820x690")
    box = ttk.Frame(win, padding=14)
    box.pack(fill="both", expand=True)

    user = tk.StringVar(value=settings.get("username", ""))
    dataset = tk.StringVar(value=settings.get("reference_dataset", ""))
    language = tk.StringVar(value=settings.get("language", "日语"))
    output = tk.StringVar(value=app.v["output"].get())
    token = tk.StringVar()
    seed = tk.StringVar(value="16261109")
    ttk.Label(box, text="免费 GPU 作业按 Kaggle Notebook 运行；本机不下载模型。").pack(anchor="w", pady=(0, 8))
    ttk.Label(box, text="Kaggle 用户名").pack(anchor="w")
    ttk.Entry(box, textvariable=user).pack(fill="x", pady=(0, 8))
    ttk.Label(box, text="1626 原声私有 Dataset（用户名/数据集slug）").pack(anchor="w")
    ttk.Entry(box, textvariable=dataset).pack(fill="x", pady=(0, 8))
    ttk.Label(box, text="配音语言与语气预设（不会上传模板音频）").pack(anchor="w")
    ttk.Combobox(box, textvariable=language, values=("日语","英语","法语","德语","印尼语","粤语/中文"), state="readonly").pack(fill="x", pady=(0, 8))
    ttk.Label(box, text="Kaggle API Key（本机 Windows 凭据库保存；不写入设置文件）").pack(anchor="w")
    ttk.Entry(box, textvariable=token, show="•").pack(fill="x", pady=(0, 5))
    ttk.Button(box, text="安全保存 Kaggle API Key", command=lambda: save_key()).pack(anchor="w", pady=(0, 8))
    ttk.Label(box, text="讲稿（每次任务会提交为私有 Notebook；运行结束后自动删除 Notebook）").pack(anchor="w")
    text_box = tk.Text(box, height=15, wrap="word")
    text_box.pack(fill="both", expand=True, pady=(0, 8))
    line = ttk.Frame(box)
    line.pack(fill="x", pady=4)
    ttk.Label(line, text="随机种子").pack(side="left")
    ttk.Entry(line, textvariable=seed, width=12).pack(side="left", padx=6)
    ttk.Label(line, text="输出目录").pack(side="left", padx=(14, 4))
    ttk.Entry(line, textvariable=output).pack(side="left", fill="x", expand=True)
    ttk.Button(line, text="选择", command=lambda: choose_output()).pack(side="left", padx=(5, 0))
    status = tk.StringVar(value="准备就绪。需要本人 Kaggle 账号及获授权的私有参考音频 Dataset。")
    ttk.Label(box, textvariable=status, wraplength=760).pack(anchor="w", pady=6)
    run_button = ttk.Button(box, text="提交 Kaggle 免费 GPU 生成", command=lambda: submit())
    run_button.pack(anchor="e", pady=(5, 0))

    def save_key():
        username = user.get().strip()
        value = token.get().strip()
        if not username or not value:
            messagebox.showinfo("需要账号信息", "请输入 Kaggle 用户名和 API Key。", parent=win)
            return
        try:
            import keyring
            keyring.set_password(KEYRING_SERVICE, username, value)
            token.set("")
            _save_settings({"username": username, "reference_dataset": dataset.get().strip(), "language": language.get()})
            status.set("API Key 已保存到本机 Windows 凭据库；设置文件中不保存密钥。")
        except Exception as exc:
            messagebox.showerror("安全保存失败", str(exc), parent=win)

    def choose_output():
        chosen = filedialog.askdirectory(parent=win, initialdir=output.get() or str(Path.home()))
        if chosen:
            output.set(chosen)

    def submit():
        username = user.get().strip()
        reference_dataset = dataset.get().strip()
        script = text_box.get("1.0", "end").strip()
        try:
            seed_value = int(seed.get().strip())
        except ValueError:
            messagebox.showerror("种子格式", "随机种子请输入整数。", parent=win)
            return
        if not username or not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+", reference_dataset):
            messagebox.showerror("缺少设置", "请输入 Kaggle 用户名和私有 Dataset 标识。", parent=win)
            return
        if not script:
            messagebox.showinfo("缺少讲稿", "请粘贴需要生成的完整文本。", parent=win)
            return
        try:
            import keyring
            api_key = keyring.get_password(KEYRING_SERVICE, username)
        except Exception as exc:
            messagebox.showerror("凭据读取失败", str(exc), parent=win)
            return
        if not api_key:
            messagebox.showinfo("还没保存 API Key", "先粘贴 API Key 并点击“安全保存”。", parent=win)
            return

        _save_settings({"username": username, "reference_dataset": reference_dataset, "language": language.get()})
        target_dir = Path(output.get()).expanduser()
        target_dir.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex[:10]
        run_button.state(["disabled"])
        status.set("正在提交私有 Kaggle GPU 作业…")

        def work():
            task_root = DATA / "kaggle_voice_jobs" / job_id
            task_root.mkdir(parents=True, exist_ok=True)
            env = os.environ.copy()
            env["KAGGLE_USERNAME"] = username
            env["KAGGLE_KEY"] = api_key
            kernel_ref = None
            try:
                kernel_ref, slug = _job_files(task_root, username, reference_dataset, script, seed_value, job_id, language.get())
                _run_cli(["kernels", "push", "-p", str(task_root)], env, timeout=600)
                win.after(0, lambda: status.set("GPU 作业已提交；等待 Kaggle 完成…"))
                deadline = time.time() + 9 * 60 * 60
                while time.time() < deadline:
                    state = _run_cli(["kernels", "status", kernel_ref], env, timeout=180).upper()
                    if "COMPLETE" in state:
                        break
                    if any(word in state for word in ("ERROR", "FAILED", "CANCELLED")):
                        raise RuntimeError("Kaggle Notebook 执行失败：" + state[-500:])
                    time.sleep(30)
                else:
                    raise TimeoutError("Kaggle 作业超过 9 小时会话上限。")
                result_dir = task_root / "output"
                result_dir.mkdir(exist_ok=True)
                _run_cli(["kernels", "output", kernel_ref, "-p", str(result_dir)], env, timeout=900)
                wavs = list(result_dir.rglob("*.wav"))
                if not wavs:
                    raise RuntimeError("Notebook 已结束，但没有找到 WAV 输出。")
                final_path = target_dir / f"YangNing_VoxCPM2_1626_{job_id}.wav"
                shutil.copy2(wavs[0], final_path)
                win.after(0, lambda p=final_path: done(p))
            except Exception as exc:
                win.after(0, lambda e=str(exc): failed(e))
            finally:
                if kernel_ref:
                    try:
                        _run_cli(["kernels", "delete", kernel_ref, "--yes"], env, timeout=180)
                    except Exception:
                        pass
                shutil.rmtree(task_root, ignore_errors=True)
                api_key = None
                env.pop("KAGGLE_KEY", None)

        def done(path):
            run_button.state(["!disabled"])
            app.v["audio"].set(str(path))
            status.set(f"生成完成，已载入工作室配音栏：{path}")
            messagebox.showinfo("WAV 已生成", f"文件已保存：\n{path}", parent=win)

        def failed(error):
            run_button.state(["!disabled"])
            status.set("任务失败。")
            messagebox.showerror("Kaggle 任务失败", error, parent=win)

        threading.Thread(target=work, daemon=True).start()
