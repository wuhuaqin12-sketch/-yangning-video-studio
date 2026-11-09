"""Optional cloud voice window. All Tk operations stay on the UI thread."""
import json
import math
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
from voice_prosody import default_template

DATA = Path(os.environ.get("YANGNING_CLOUD_DATA_DIR", str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "YangNingStudio")))
SETTINGS = DATA / "kaggle_voice_settings.json"
KEYRING_SERVICE = os.environ.get("YANGNING_CLOUD_CREDENTIAL_SERVICE", "YangNingStudio-Kaggle")


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
    previous = getattr(app, "_cloud_voice_window", None)
    if previous is not None:
        try:
            if previous.winfo_exists():
                previous.lift()
                return
        except tk.TclError:
            pass
    settings = _load_settings()
    if settings.get("speed_standard_version") != 2:
        settings["tempo_by_language"] = {name: 1.0 for name in PROFILES}
        settings["speed_standard_version"] = 2
        save_json(SETTINGS, settings)
    win = tk.Toplevel(app.root)
    app._cloud_voice_window = win
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
    tempo = tk.StringVar(value=str(settings.get("tempo_by_language", {}).get(language.get(), profile_for(language.get())["tempo"])))
    template = tk.StringVar(value=settings.get("prosody_templates", {}).get(language.get(), default_template(language.get())))
    mode = tk.StringVar(value="full")
    export_movie = tk.BooleanVar(value=False)
    source_video = tk.StringVar(value=app.v["video"].get() if "video" in app.v else "")
    source_audio = tk.StringVar()
    source_srt = tk.StringVar()
    range_start = tk.StringVar(value="0")
    range_end = tk.StringVar(value="1")
    output = tk.StringVar(value=settings.get("output_dir", app.v["output"].get()))
    token = tk.StringVar()
    seed = tk.StringVar(value=str(settings.get("seed", 16261109)))
    profile_info = tk.StringVar()
    status = tk.StringVar(value="准备就绪。生成结果按试听保存，音色和读音需听检确认。")
    last_audio = settings.get("last_audio", "")
    last_video = settings.get("last_video", "")

    ttk.Label(box, text="1626老师原声 · 保留自然停顿 · 轻度降噪", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
    ttk.Label(box, text="模板只分析停顿和相对起伏，再转成语气提示；不作为音色或续写音频。逐句语调复刻尚未实现。", wraplength=740).pack(anchor="w", pady=(4, 10))
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
    ttk.Label(line, text="倍数").pack(side="left")
    ttk.Combobox(line, textvariable=tempo, values=("0.5", "0.75", "0.84", "0.9", "1.0", "1.1", "1.25", "1.5", "2.0"), width=7).pack(side="left", padx=8)
    ttk.Label(line, textvariable=profile_info).pack(side="left")
    combo.bind("<<ComboboxSelected>>", lambda e: update_profile(True))
    template_row = ttk.LabelFrame(box, text="语气参考（音色始终使用1626）", padding=8)
    template_row.pack(fill="x", pady=5)
    ttk.Entry(template_row, textvariable=template).pack(side="left", fill="x", expand=True)
    ttk.Button(template_row, text="选择模板", command=lambda: choose_media(template, [("音频", "*.wav *.mp3 *.m4a")])).pack(side="left", padx=5)
    ttk.Button(template_row, text="恢复本语言模板", command=lambda: template.set(default_template(language.get()))).pack(side="left")
    ttk.Label(box, text="日语用日语模板；英语、法语、德语用英语模板。粤语、印尼语可另选模板；留空使用自然语气。模板不会改变所选倍数。", wraplength=740).pack(anchor="w")
    choices = ttk.Frame(box)
    choices.pack(fill="x", pady=5)
    ttk.Radiobutton(choices, text="修改全文后重新生成", variable=mode, value="full").pack(side="left")
    ttk.Radiobutton(choices, text="只重做选定句段并导出完整短片", variable=mode, value="partial", command=lambda: export_movie.set(True)).pack(side="left", padx=8)
    source = ttk.LabelFrame(box, text="合成完整短片", padding=8)
    source.pack(fill="x", pady=6)
    source.columnconfigure(1, weight=1)
    for row, label, variable, types in (
        (0, "当前短片MP4", source_video, [("视频", "*.mp4 *.mov *.mkv")]),
        (1, "独立配音（可留空）", source_audio, [("音频", "*.wav *.mp3 *.m4a")]),
        (2, "当前成片配套SRT（可选）", source_srt, [("字幕", "*.srt")]),
    ):
        ttk.Label(source, text=label).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(source, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(source, text="选择", command=lambda v=variable, t=types: choose_media(v, t)).grid(row=row, column=2)
    selection = ttk.Frame(source)
    selection.grid(row=3, column=0, columnspan=3, sticky="ew", pady=4)
    ttk.Label(selection, text="替换起点（秒）").pack(side="left")
    ttk.Entry(selection, textvariable=range_start, width=9).pack(side="left", padx=4)
    ttk.Label(selection, text="终点（秒）").pack(side="left")
    ttk.Entry(selection, textvariable=range_end, width=9).pack(side="left", padx=4)
    ttk.Button(selection, text="从字幕选句段", command=lambda: select_cues()).pack(side="left", padx=6)
    ttk.Checkbutton(source, text="全文模式也同时导出完整短片", variable=export_movie).grid(row=4, column=0, columnspan=3, sticky="w")
    ttk.Label(source, text="局部模式请选包含前后自然停顿的完整句段。画面随新配音调整时长；输出新SRT。画面里的旧烧录字幕需使用干净源视频处理。", wraplength=720).grid(row=5, column=0, columnspan=3, sticky="w", pady=4)
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
    ttk.Button(actions, text="播放完整短片", command=lambda: play_last(True)).pack(side="left", padx=5)
    resume = ttk.Button(actions, text="恢复最近任务", command=lambda: start(True))
    resume.pack(side="left", padx=8)
    submit = ttk.Button(actions, text="生成克隆试听", command=lambda: start(False))
    submit.pack(side="right")

    def update_profile(reset=False):
        if reset:
            tempo.set(str(settings.get("tempo_by_language", {}).get(language.get(), profile_for(language.get())["tempo"])))
            template.set(settings.get("prosody_templates", {}).get(language.get(), default_template(language.get())))
        profile_info.set("保音高 · 柔和连贯 · 停顿保留")

    def remember():
        settings.update(username=username.get().strip(), reference_dataset=dataset.get().strip(),
                        language=language.get(), output_dir=output.get(), seed=seed.get())
        settings.setdefault("tempo_by_language", {})[language.get()] = float(tempo.get())
        settings.setdefault("prosody_templates", {})[language.get()] = template.get()
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

    def choose_media(variable, types):
        value = filedialog.askopenfilename(parent=win, filetypes=types + [("所有文件", "*.*")])
        if value:
            variable.set(value)

    def select_cues():
        from voice_clip_edit import read_srt
        if not source_srt.get():
            choose_media(source_srt, [("字幕", "*.srt")])
        if not source_srt.get():
            return
        try:
            cues = read_srt(source_srt.get())
        except Exception as exc:
            messagebox.showerror("字幕未打开", str(exc), parent=win)
            return
        chooser = tk.Toplevel(win)
        chooser.title("选择连续的完整句段")
        chooser.geometry("760x440")
        listing = tk.Listbox(chooser, selectmode="extended", exportselection=False)
        listing.pack(fill="both", expand=True, padx=10, pady=10)
        for cue in cues:
            listing.insert("end", f"{cue['start']:.3f}–{cue['end']:.3f}  {cue['text'].replace(chr(10), ' ')}")
        def take():
            selected = list(listing.curselection())
            if not selected or selected != list(range(selected[0], selected[-1] + 1)):
                messagebox.showinfo("请选择连续句段", "可选择一句或连续的几句。", parent=chooser)
                return
            range_start.set(str(cues[selected[0]]["start"]))
            range_end.set(str(cues[selected[-1]]["end"]))
            text_box.delete("1.0", "end")
            text_box.insert("1.0", " ".join(cues[i]["text"] for i in selected))
            mode.set("partial")
            export_movie.set(True)
            chooser.destroy()
        ttk.Button(chooser, text="载入选定句段，修改正文", command=take).pack(pady=8)

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
                selected_tempo = float(tempo.get())
                profile_for(language.get(), selected_tempo)
                edit = None
                if mode.get() == "partial" or export_movie.get():
                    if not Path(source_video.get()).is_file():
                        raise ValueError("请先选择需要重新合成的当前完整短片。")
                    a, b = (0.0, 1.0) if mode.get() == "full" else (float(range_start.get()), float(range_end.get()))
                    if mode.get() == "partial" and (not math.isfinite(a + b) or not 0 <= a < b):
                        raise ValueError("局部替换需要有效的起点和终点。")
                    edit = {"mode": mode.get(), "video": source_video.get(), "audio": source_audio.get(), "srt": source_srt.get(), "start": a, "end": b}
                manifest = prepare_job(DATA / "kaggle_voice_jobs", user, dataset.get().strip(),
                                       text_box.get("1.0", "end"), language.get(), int(seed.get()), output.get(), tempo=selected_tempo, edit=edit, prosody_template=template.get() or None)
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

    def play_last(movie=False):
        path = last_video if movie else last_audio
        if not path or not Path(path).is_file():
            messagebox.showinfo("还没有结果", "先完成对应的生成或合成任务。", parent=win)
            return
        if os.name == "nt":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])

    def poll():
        nonlocal running, last_audio, last_video
        try:
            while True:
                kind, payload = events.get_nowait()
                if kind in ("status", "warning"):
                    status.set(payload)
                elif kind == "done":
                    running = False
                    last_audio = payload.get("edited_audio", payload["yangning_final.wav"])
                    last_video = payload.get("edited_video", "")
                    settings["last_audio"] = last_audio
                    settings["last_video"] = last_video
                    save_json(SETTINGS, settings)
                    app.v["audio"].set(last_audio)
                    if last_video:
                        app.v["video"].set(last_video)
                        if "target_srt" in app.v:
                            app.v["target_srt"].set(payload["edited_srt"])
                    # The WAV already has its language-specific slowdown. Prevent a second
                    # automatic speed/pause pass when it enters the video workflow.
                    if "speed" in app.v:
                        app.v["speed"].set("1.0")
                    if "trim" in app.v:
                        app.v["trim"].set(False)
                    if hasattr(app, "auto_cut"):
                        app.auto_cut.set(False)
                    status.set(("完整短片已导出，可播放检查接缝；新句段字幕时间仍需校对。" if last_video else "试听WAV已载入配音栏。") + " 已保留原版本及制作记录，成片倍速设为1.0避免重复变速。")
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
