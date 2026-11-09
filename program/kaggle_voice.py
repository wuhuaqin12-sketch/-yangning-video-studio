"""Optional cloud voice window. All Tk operations stay on the UI thread."""
import json
import os
import queue
import re
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from cloud_voice_core import prepare_job, run_job, save_json, script_from_text
from voxcpm_kaggle_worker import PROFILES, profile_for

DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "YangNingStudio"
SETTINGS = DATA / "kaggle_voice_settings.json"
KEYRING_SERVICE = "YangNingStudio-Kaggle"


def _load_settings():
    try:
        value = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _vault():
    if os.name != "nt":
        raise RuntimeError("此工作室版本使用Windows凭据库保存令牌，请在Windows版本中配置。")
    from keyring.backends.Windows import WinVaultKeyring
    return WinVaultKeyring()


def open_kaggle_voice(app, parent=None):
    settings = _load_settings()
    win = tk.Toplevel(app.root)
    win.title("免费云端语音克隆 · VoxCPM2")
    win.geometry("840x780")
    win.minsize(760, 650)
    outer = ttk.Frame(win)
    outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(outer, highlightthickness=0)
    scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    box = ttk.Frame(canvas, padding=14)
    item = canvas.create_window((0, 0), window=box, anchor="nw")
    box.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
    events = queue.Queue()
    running = False

    username = tk.StringVar(value=settings.get("username", ""))
    dataset = tk.StringVar(value=settings.get("reference_dataset", ""))
    saved_language = settings.get("language", "日语")
    language = tk.StringVar(value=saved_language if saved_language in PROFILES else "日语")
    output = tk.StringVar(value=settings.get("output_dir", app.v["output"].get()))
    token = tk.StringVar()
    seed = tk.StringVar(value=str(settings.get("seed", 16261109)))
    profile_info = tk.StringVar()
    status = tk.StringVar(value="准备就绪。生成结果按试听保存，音色和读音需听检确认。")
    last_audio = settings.get("last_audio", "")

    ttk.Label(box, text="1626老师原声 · 保留自然停顿 · 轻度降噪", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
    ttk.Label(box, text="语气通过文字指令提示模型；模板逐句起伏匹配尚未实现，具体效果需试听确认。", wraplength=740).pack(anchor="w", pady=(4, 10))
    connection = ttk.LabelFrame(box, text="首次连接Kaggle", padding=10)
    connection.pack(fill="x", pady=(0, 10))
    connection.columnconfigure(1, weight=1)
    for row, label, variable in ((0, "本人Kaggle用户名", username), (1, "私有数据集（用户名/slug）", dataset), (2, "访问令牌 / API Key", token)):
        ttk.Label(connection, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(connection, textvariable=variable, show="•" if row == 2 else "").grid(row=row, column=1, sticky="ew", pady=4)
    ttk.Button(connection, text="安全保存连接", command=lambda: save_connection()).grid(row=3, column=1, sticky="e", pady=4)
    ttk.Label(connection, text="令牌仅保存在这台电脑的Windows凭据库。1626参考文件需命名为1626_reference.wav，保留原始文件内容。", wraplength=720).grid(row=4, column=0, columnspan=2, sticky="w", pady=4)

    line = ttk.Frame(box)
    line.pack(fill="x", pady=5)
    ttk.Label(line, text="配音语言").pack(side="left")
    combo = ttk.Combobox(line, textvariable=language, values=tuple(PROFILES), state="readonly", width=12)
    combo.pack(side="left", padx=8)
    ttk.Label(line, textvariable=profile_info).pack(side="left")
    combo.bind("<<ComboboxSelected>>", lambda e: update_profile())
    buttons = ttk.Frame(box)
    buttons.pack(fill="x", pady=4)
    ttk.Label(buttons, text="朗读正文").pack(side="left")
    ttk.Button(buttons, text="导入TXT / SRT", command=lambda: import_script()).pack(side="right")
    text_box = tk.Text(box, height=12, wrap="word", undo=True)
    text_box.pack(fill="both", expand=True, pady=(0, 8))
    line = ttk.Frame(box)
    line.pack(fill="x", pady=4)
    ttk.Label(line, text="输出目录").pack(side="left")
    ttk.Entry(line, textvariable=output).pack(side="left", fill="x", expand=True, padx=8)
    ttk.Button(line, text="选择", command=lambda: choose_output()).pack(side="left")
    advanced = ttk.Frame(box)
    advanced.pack(fill="x", pady=4)
    ttk.Label(advanced, text="随机种子").pack(side="left")
    ttk.Entry(advanced, textvariable=seed, width=14).pack(side="left", padx=8)
    ttk.Label(advanced, text="-1为随机；同种子不保证跨设备听感完全相同。").pack(side="left")
    ttk.Label(box, textvariable=status, wraplength=740).pack(anchor="w", pady=8)
    actions = ttk.Frame(box)
    actions.pack(fill="x", pady=5)
    preview = ttk.Button(actions, text="试听最近WAV", command=lambda: play_last())
    preview.pack(side="left")
    resume = ttk.Button(actions, text="恢复最近任务", command=lambda: start(True))
    resume.pack(side="left", padx=8)
    submit = ttk.Button(actions, text="生成克隆试听", command=lambda: start(False))
    submit.pack(side="right")

    def update_profile():
        profile = profile_for(language.get())
        profile_info.set(f"{profile['tempo']}倍保音高 · 柔和连贯 · 停顿保留")

    def remember():
        settings.update(username=username.get().strip(), reference_dataset=dataset.get().strip(),
                        language=language.get(), output_dir=output.get(), seed=seed.get())
        save_json(SETTINGS, settings)

    def save_connection():
        user = username.get().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", user):
            messagebox.showinfo("需要用户名", "请输入本人Kaggle用户名。", parent=win)
            return
        try:
            vault = _vault()
            if token.get().strip():
                vault.set_password(KEYRING_SERVICE, user, token.get().strip())
                token.set("")
            elif not vault.get_password(KEYRING_SERVICE, user):
                raise ValueError("请先输入本人Kaggle访问令牌。")
            remember()
            status.set("连接信息已保存。令牌已存入Windows凭据库。")
        except Exception:
            messagebox.showerror("连接未保存", "请检查用户名、访问令牌和Windows凭据库。密钥不会写入普通设置文件。", parent=win)

    def import_script():
        path = filedialog.askopenfilename(parent=win, filetypes=[("朗读稿", "*.txt *.srt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8-sig")
            content = script_from_text(content)
            text_box.delete("1.0", "end")
            text_box.insert("1.0", content)
            status.set("正文已导入；SRT编号和时间码不参与朗读，佛教术语读音仍需校对。")
        except (OSError, UnicodeError, ValueError) as exc:
            messagebox.showerror("导入失败", str(exc), parent=win)

    def choose_output():
        value = filedialog.askdirectory(parent=win, initialdir=output.get() or str(Path.home()))
        if value:
            output.set(value)

    def start(recover):
        nonlocal running
        if running:
            return
        try:
            if recover:
                manifest = Path(settings.get("last_manifest", ""))
                job = json.loads(manifest.read_text(encoding="utf-8"))
                user = job["username"]
            else:
                user = username.get().strip()
            secret = _vault().get_password(KEYRING_SERVICE, user)
            if not secret:
                raise ValueError("请先为这个Kaggle用户名安全保存访问令牌。")
            if not recover:
                manifest = prepare_job(DATA / "kaggle_voice_jobs", user, dataset.get().strip(),
                                       text_box.get("1.0", "end"), language.get(), int(seed.get()), output.get())
                settings["last_manifest"] = str(manifest)
                remember()
        except Exception as exc:
            messagebox.showerror("还不能提交", str(exc) if isinstance(exc, (ValueError, OSError)) else "请检查连接信息和最近任务记录。", parent=win)
            return
        running = True
        submit.state(["disabled"])
        resume.state(["disabled"])
        status.set("正在恢复云端任务…" if recover else "正在准备私有GPU作业…")

        def work():
            try:
                run_job(manifest, secret, events.put)
            except Exception as exc:
                events.put(("error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def play_last():
        if not last_audio or not Path(last_audio).is_file():
            messagebox.showinfo("还没有WAV", "先完成一个生成任务。", parent=win)
            return
        if os.name == "nt":
            os.startfile(last_audio)
        else:
            subprocess.Popen(["xdg-open", last_audio])

    def poll():
        nonlocal running, last_audio
        try:
            while True:
                kind, payload = events.get_nowait()
                if kind in ("status", "warning"):
                    status.set(payload)
                elif kind == "done":
                    running = False
                    last_audio = payload["yangning_final.wav"]
                    settings["last_audio"] = last_audio
                    save_json(SETTINGS, settings)
                    app.v["audio"].set(last_audio)
                    # The WAV already has its language-specific slowdown. Prevent a second
                    # automatic speed/pause pass when it enters the video workflow.
                    if "speed" in app.v:
                        app.v["speed"].set("1.0")
                    if "trim" in app.v:
                        app.v["trim"].set(False)
                    if hasattr(app, "auto_cut"):
                        app.auto_cut.set(False)
                    status.set("试听WAV已载入配音栏。已保留停顿并将成片倍速设为1.0，避免重复变速；制作记录和原始WAV已保存。")
                    submit.state(["!disabled"])
                    resume.state(["!disabled"])
                elif kind == "error":
                    running = False
                    submit.state(["!disabled"])
                    resume.state(["!disabled"])
                    status.set("任务未完成，记录已保留。可点击恢复最近任务；不会重新提交同一作业。")
                    messagebox.showerror("云端任务未完成", payload, parent=win)
        except queue.Empty:
            pass
        if win.winfo_exists():
            win.after(150, poll)

    update_profile()
    win.after(150, poll)
