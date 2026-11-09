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
from voice_prosody import default_template
from japanese_pronunciation import READINGS, parse_overrides, reading_plan
from voice_adjust import STYLE_OPTIONS, interpret_instruction, adjust_audio

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
    mode = tk.StringVar(value="generate")
    source_audio = tk.StringVar(value=settings.get("last_audio", ""))
    source_srt = tk.StringVar()
    range_start, range_end = tk.StringVar(value="0"), tk.StringVar(value="1")
    pronunciation_enabled = tk.BooleanVar(value=settings.get("japanese_pronunciation_enabled",True))
    japanese_readings = settings.get("japanese_pronunciation_overrides",{})
    output = tk.StringVar(value=settings.get("output_dir", app.v["output"].get()))
    token = tk.StringVar()
    seed = tk.StringVar(value=str(settings.get("seed", 16261109)))
    profile_info = tk.StringVar()
    status = tk.StringVar(value="准备就绪。生成结果按试听保存，音色和读音需听检确认。")
    last_audio = settings.get("last_audio", "")
    delivery_options = []
    more = tk.Toplevel(win)
    more.title("更多设置")
    more.geometry("820x720")
    more.withdraw()
    more.protocol("WM_DELETE_WINDOW", more.withdraw)
    tabs = ttk.Notebook(more)
    tabs.pack(fill="both", expand=True, padx=12, pady=12)
    connection_tab, language_tab, edit_tab = [ttk.Frame(tabs, padding=10) for _ in range(3)]
    for pane, label in ((connection_tab,"连接与输出"),(language_tab,"模板与读音"),(edit_tab,"修改原音频")):
        tabs.add(pane, text=label)
    ttk.Button(box,text="更多设置 ⋯",command=lambda: (more.deiconify(), more.lift())).pack(anchor="e")

    ttk.Label(box, text="1626老师原声 · 保留自然停顿 · 轻度降噪", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
    ttk.Label(box, text="模板只分析停顿和相对起伏，再转成语气提示；不作为音色或续写音频。逐句语调复刻尚未实现。", wraplength=740).pack(anchor="w", pady=(4, 10))
    connection = ttk.LabelFrame(connection_tab, text="首次连接Kaggle", padding=10)
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
    template_row = ttk.LabelFrame(language_tab, text="语气参考（音色始终使用1626）", padding=8)
    template_row.pack(fill="x", pady=5)
    ttk.Entry(template_row, textvariable=template).pack(side="left", fill="x", expand=True)
    ttk.Button(template_row, text="选择模板", command=lambda: choose_media(template, [("音频", "*.wav *.mp3 *.m4a")])).pack(side="left", padx=5)
    ttk.Button(template_row, text="恢复本语言模板", command=lambda: template.set(default_template(language.get()))).pack(side="left")
    ttk.Label(language_tab, text="日语用日语模板；英语、法语、德语用英语模板。粤语、印尼语可另选模板；留空使用自然语气。模板不会改变所选倍数。", wraplength=740).pack(anchor="w")
    ttk.Label(box, text="这里只生成WAV音频；音画同步和成片合成请在杨宁工作室完成。", wraplength=740).pack(anchor="w", pady=6)
    choices = ttk.Frame(edit_tab)
    choices.pack(fill="x", pady=6)
    for label, value in (("生成新音频", "generate"), ("修改全文后重新生成", "full"), ("局部改读音并接回原音频", "partial")):
        ttk.Radiobutton(choices, text=label, variable=mode, value=value, command=lambda: update_mode()).pack(side="left", padx=(0,12))
    pronunciation_row = ttk.Frame(language_tab)
    ttk.Checkbutton(pronunciation_row,text="日语佛教术语读音校正",variable=pronunciation_enabled).pack(side="left")
    ttk.Button(pronunciation_row,text="预览实际朗读稿",command=lambda: preview_reading()).pack(side="left",padx=5)
    ttk.Button(pronunciation_row,text="编辑术语读音表",command=lambda: edit_readings()).pack(side="left")
    correction = ttk.LabelFrame(edit_tab, text="原音频与替换句段", padding=8)
    correction.columnconfigure(1, weight=1)
    for row, label, variable, types in (
        (0, "需要修改的原音频", source_audio, [("音频", "*.wav *.mp3 *.m4a")]),
        (1, "配套SRT（可选）", source_srt, [("字幕", "*.srt")]),
    ):
        ttk.Label(correction, text=label).grid(row=row, column=0, sticky="w")
        ttk.Entry(correction, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=5, pady=4)
        ttk.Button(correction, text="选择", command=lambda v=variable,t=types: choose_media(v,t)).grid(row=row, column=2)
    selection = ttk.Frame(correction)
    selection.grid(row=2, column=0, columnspan=3, sticky="ew", pady=4)
    ttk.Label(selection, text="替换起点（秒）").pack(side="left")
    ttk.Entry(selection, textvariable=range_start, width=9).pack(side="left", padx=5)
    ttk.Label(selection, text="终点（秒）").pack(side="left")
    ttk.Entry(selection, textvariable=range_end, width=9).pack(side="left", padx=5)
    ttk.Button(selection, text="从SRT选择句段", command=lambda: select_cues()).pack(side="left")
    ttk.Label(correction, text="选择包含前后停顿的完整句子，正文只填写修改后的句段。自动匹配音量、在静音接点平滑连接，导出完整WAV和接缝试听，保留原文件。", wraplength=720).grid(row=3,column=0,columnspan=3,sticky="w",pady=4)
    buttons = ttk.Frame(box)
    buttons.pack(fill="x", pady=4)
    script_label = ttk.Label(buttons, text="朗读正文")
    script_label.pack(side="left")
    ttk.Button(buttons, text="导入TXT / SRT", command=lambda: import_script()).pack(side="right")
    text_box = tk.Text(box, height=12, wrap="word", undo=True)
    text_box.pack(fill="both", expand=True, pady=(0, 8))
    line = ttk.Frame(connection_tab)
    line.pack(fill="x", pady=4)
    ttk.Label(line, text="输出目录").pack(side="left")
    ttk.Entry(line, textvariable=output).pack(side="left", fill="x", expand=True, padx=8)
    ttk.Button(line, text="选择", command=lambda: choose_output()).pack(side="left")
    advanced = ttk.Frame(connection_tab)
    advanced.pack(fill="x", pady=4)
    ttk.Label(advanced, text="随机种子").pack(side="left")
    ttk.Entry(advanced, textvariable=seed, width=14).pack(side="left", padx=8)
    ttk.Label(advanced, text="-1为随机；同种子不保证跨设备听感完全相同。").pack(side="left")
    ttk.Label(box, textvariable=status, wraplength=740).pack(anchor="w", pady=8)
    actions = ttk.Frame(box)
    actions.pack(fill="x", pady=5)
    preview = ttk.Button(actions, text="试听最近WAV", command=lambda: play_last())
    preview.pack(side="left")
    ttk.Button(actions,text="音频微调 / 语气重生成",command=lambda: adjustment_dialog()).pack(side="left",padx=6)
    resume = ttk.Button(actions, text="恢复最近任务", command=lambda: start(True))
    resume.pack(side="left", padx=8)
    submit = ttk.Button(actions, text="生成音频", command=lambda: start(False))
    submit.pack(side="right")

    def update_mode():
        if mode.get() == "partial":
            if not source_audio.get():
                source_audio.set(last_audio)
            correction.pack(fill="x", pady=5)
            script_label.configure(text="修改后的句段正文")
            submit.configure(text="重生成句段并连接完整音频")
        else:
            correction.pack_forget()
            script_label.configure(text="修改后的完整正文" if mode.get() == "full" else "朗读正文")
            submit.configure(text="全文重新生成" if mode.get() == "full" else "生成音频")

    def update_profile(reset=False):
        if reset:
            tempo.set(str(settings.get("tempo_by_language", {}).get(language.get(), profile_for(language.get())["tempo"])))
            template.set(settings.get("prosody_templates", {}).get(language.get(), default_template(language.get())))
        profile_info.set("保音高 · 柔和连贯 · 停顿保留")
        if language.get() == "日语":
            pronunciation_row.pack(fill="x",pady=4)
        else:
            pronunciation_row.pack_forget()

    def remember():
        settings.update(username=username.get().strip(), reference_dataset=dataset.get().strip(),
                        language=language.get(), output_dir=output.get(), seed=seed.get())
        settings.setdefault("tempo_by_language", {})[language.get()] = float(tempo.get())
        settings.setdefault("prosody_templates", {})[language.get()] = template.get()
        settings["japanese_pronunciation_enabled"] = pronunciation_enabled.get()
        settings["japanese_pronunciation_overrides"] = japanese_readings
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

    def choose_output():
        value = filedialog.askdirectory(parent=win, initialdir=output.get() or str(Path.home()))
        if value:
            output.set(value)

    def preview_reading():
        try:
            original = script_from_text(text_box.get("1.0","end"))
            plan = reading_plan(original,japanese_readings) if pronunciation_enabled.get() else {"reading_text":original,"replacements":[],"needs_context_review":[]}
        except ValueError as exc:
            messagebox.showinfo("请先输入正文",str(exc),parent=win)
            return
        popup = tk.Toplevel(win)
        popup.title("实际朗读稿 · 原文汉字不变")
        popup.geometry("800x620")
        note = "已替换："+"、".join(f"{x['term']}→{x['reading']}" for x in plan["replacements"])
        if plan["needs_context_review"]:
            note += "\n需按语境确认："+"、".join(plan["needs_context_review"])+"（可在读音表添加）"
        ttk.Label(popup,text=note or "没有术语替换。",wraplength=760).pack(fill="x",padx=12,pady=8)
        pane = tk.Text(popup,wrap="word")
        pane.pack(fill="both",expand=True,padx=12,pady=8)
        pane.insert("1.0",plan["reading_text"])
        pane.configure(state="disabled")
        ttk.Label(popup,text="这是送入模型的读音稿；原稿和字幕保留汉字。假名仍不能保证实际音频完全读对，生成后需试听。",wraplength=760).pack(padx=12,pady=8)

    def edit_readings():
        popup = tk.Toplevel(win)
        popup.title("日语术语读音表")
        popup.geometry("780x620")
        ttk.Label(popup,text="内置项目读音（只读；部分术语存在其他合法读法）").pack(anchor="w",padx=10,pady=5)
        fixed = tk.Text(popup,height=9,wrap="word")
        fixed.pack(fill="both",expand=True,padx=10)
        fixed.insert("1.0","\n".join(f"{term}={reading}" for term,reading in READINGS.items()))
        fixed.configure(state="disabled")
        ttk.Label(popup,text="自定义优先读音：每行填写“汉字词语=假名读音”，可新增或覆盖内置词。").pack(anchor="w",padx=10,pady=6)
        custom = tk.Text(popup,height=9,wrap="word")
        custom.pack(fill="both",expand=True,padx=10)
        custom.insert("1.0","\n".join(f"{term}={reading}" for term,reading in japanese_readings.items()))
        def save():
            nonlocal japanese_readings
            try:
                value = parse_overrides(custom.get("1.0","end"))
            except ValueError as exc:
                messagebox.showerror("读音表未保存",str(exc),parent=popup)
                return
            japanese_readings = value
            settings["japanese_pronunciation_overrides"] = value
            save_json(SETTINGS,settings)
            popup.destroy()
        ttk.Button(popup,text="保存读音表",command=save).pack(pady=10)

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
        chooser.title("选择需要改读音的连续句段")
        chooser.geometry("760x440")
        listing = tk.Listbox(chooser, selectmode="extended", exportselection=False)
        listing.pack(fill="both",expand=True,padx=10,pady=10)
        for cue in cues:
            listing.insert("end", f"{cue['start']:.3f}–{cue['end']:.3f}  {cue['text'].replace(chr(10),' ')}")
        def take():
            selected = list(listing.curselection())
            if not selected or selected != list(range(selected[0],selected[-1]+1)):
                messagebox.showinfo("请选择连续句段", "请选择一句或连续几句。", parent=chooser)
                return
            range_start.set(str(cues[selected[0]]["start"]))
            range_end.set(str(cues[selected[-1]]["end"]))
            text_box.delete("1.0","end")
            text_box.insert("1.0"," ".join(cues[i]["text"] for i in selected))
            chooser.destroy()
        ttk.Button(chooser,text="载入句段后修改正文",command=take).pack(pady=8)

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
                if mode.get() == "partial":
                    if not Path(source_audio.get()).is_file():
                        raise ValueError("局部改读音需要先选择原音频。")
                    edit = {"kind":"audio", "mode":"partial", "audio":source_audio.get(), "srt":source_srt.get(), "start":float(range_start.get()), "end":float(range_end.get())}
                manifest = prepare_job(DATA / "kaggle_voice_jobs", user, dataset.get().strip(),
                                       text_box.get("1.0", "end"), language.get(), int(seed.get()), output.get(), tempo=selected_tempo, edit=edit, prosody_template=template.get() or None,
                                       pronunciation_enabled=pronunciation_enabled.get(), japanese_readings=japanese_readings, style_options=delivery_options)
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
                run_job(manifest, secret, events.put, audio_only=True)
            except Exception as exc:
                events.put(("error", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def adjustment_dialog():
        nonlocal delivery_options
        popup = tk.Toplevel(win)
        popup.title("音频微调 · 保留原版")
        popup.geometry("760x650")
        area = ttk.Frame(popup,padding=14)
        area.pack(fill="both",expand=True)
        selected_audio = tk.StringVar(value=last_audio)
        ttk.Label(area,text="普通音频也可以选择；无需克隆文本、视频或云端GPU。").pack(anchor="w")
        row=ttk.Frame(area); row.pack(fill="x",pady=7)
        ttk.Entry(row,textvariable=selected_audio).pack(side="left",fill="x",expand=True)
        ttk.Button(row,text="选择音频",command=lambda: choose_media(selected_audio,[("音频","*.wav *.mp3 *.m4a *.flac")])).pack(side="left")
        speed, gain = tk.StringVar(value="1.0"),tk.StringVar(value="0")
        noise=tk.BooleanVar(value=False)
        row=ttk.Frame(area);row.pack(fill="x",pady=7)
        ttk.Label(row,text="速度（保音高）").pack(side="left")
        ttk.Combobox(row,textvariable=speed,values=("0.75","0.9","1.0","1.1","1.25"),width=8).pack(side="left",padx=5)
        ttk.Label(row,text="音量变化 dB").pack(side="left")
        ttk.Combobox(row,textvariable=gain,values=("-6","-2","0","2","4"),width=8).pack(side="left",padx=5)
        ttk.Checkbutton(row,text="轻度降噪",variable=noise).pack(side="left")
        ttk.Label(area,text="语气选项（需要重新生成；普通外部音频须先提供对应正文）：").pack(anchor="w",pady=(12,5))
        selected={name:tk.BooleanVar(value=name in delivery_options) for name in STYLE_OPTIONS}
        grid=ttk.Frame(area);grid.pack(fill="x")
        for i,(name,var) in enumerate(selected.items()):
            ttk.Checkbutton(grid,text=name,variable=var).grid(row=i//4,column=i%4,sticky="w",padx=5,pady=4)
        ttk.Label(area,text="快捷指令：放慢一点、加快一点、音量大一点、音量小一点、轻度降噪，以及上面的语气选项。用逗号分隔。​",wraplength=700).pack(anchor="w",pady=8)
        instructions=tk.StringVar()
        ttk.Entry(area,textvariable=instructions).pack(fill="x")
        explanation=tk.StringVar(value="未列出的自由指令不会自动执行。语气控制是模型提示，不能保证每次听感完全符合要求。")
        ttk.Label(area,textvariable=explanation,wraplength=700).pack(fill="x",pady=8)
        def parse():
            result=interpret_instruction(instructions.get())
            if result["unrecognized"]:
                messagebox.showinfo("存在未识别指令","请改用列出的选项："+"、".join(result["unrecognized"]),parent=popup)
                return
            speed.set(str(result["tempo"]));gain.set(str(result["gain_db"]));noise.set(result["denoise"])
            for name,var in selected.items():
                var.set(name in result["styles"])
            instructions.set("")
            explanation.set(f"将应用：速度{speed.get()}倍、音量{gain.get()}dB、降噪{'开' if noise.get() else '关'}。语气重生成："+"、".join(result["styles"]))
        ttk.Button(area,text="识别指令并预览动作",command=parse).pack(anchor="w")
        def local_apply():
            nonlocal running
            if running:
                messagebox.showinfo("任务进行中","请先等待当前任务完成。",parent=popup);return
            if any(v.get() for v in selected.values()):
                messagebox.showinfo("语气需要重生成","当前选择了语气选项。请使用下方语气重生成按钮，或取消语气选项后只处理速度、音量和降噪。",parent=popup);return
            if instructions.get().strip():
                messagebox.showinfo("请先预览","请先点击识别指令并预览动作，然后清空指令框；调整按上方显示的数值执行。",parent=popup);return
            try:
                values=(selected_audio.get(), output.get(),float(speed.get()),float(gain.get()),noise.get())
            except ValueError:
                messagebox.showerror("数值错误","请填写有效的速度和音量数值。",parent=popup);return
            running=True
            submit.state(["disabled"]);resume.state(["disabled"])
            status.set("正在处理已有音频，保留原文件和停顿…")
            def work():
                try:
                    result=adjust_audio(*values)
                    events.put(("adjusted",result))
                except Exception as exc:
                    events.put(("adjust_error",str(exc)))
            threading.Thread(target=work,daemon=True).start()
            popup.destroy()
        def regenerate():
            nonlocal delivery_options
            if instructions.get().strip():
                messagebox.showinfo("请先预览","先识别指令，确认选项后清空指令框。",parent=popup);return
            delivery_options=[name for name,var in selected.items() if var.get()]
            if not delivery_options:
                messagebox.showinfo("请选择语气","至少选择一项语气调整。",parent=popup);return
            # Generation uses the visible corrected text and existing partial mode,
            # never pretend to infer a transcript from an arbitrary audio file.
            if not text_box.get("1.0","end").strip():
                messagebox.showinfo("需要正文","请先在主页面填写音频对应的正文；外部音频不会自动转录。",parent=popup);return
            tempo.set(speed.get())
            if gain.get() not in ("0","0.0") or noise.get():
                messagebox.showinfo("先重生成语气","此按钮只使用语气和速度；音量与额外降噪请在生成后单独处理。",parent=popup);return
            popup.destroy()
            start(False)
        ttk.Button(area,text="仅处理已有音频 → 另存新WAV",command=local_apply).pack(fill="x",pady=(12,5))
        ttk.Button(area,text="按主页面正文 / 当前修改模式重生成语气",command=regenerate).pack(fill="x",pady=5)
        ttk.Label(area,text="原音频始终保留。不会自动裁剪停顿、改变音高，或把普通后期处理标记为语气改善。",wraplength=700).pack(anchor="w",pady=8)

    def play_last():
        path = last_audio
        if not path or not Path(path).is_file():
            messagebox.showinfo("还没有结果", "先完成对应的生成或合成任务。", parent=win)
            return
        if os.name == "nt":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])

    def poll():
        nonlocal running, last_audio
        try:
            while True:
                kind, payload = events.get_nowait()
                if kind in ("status", "warning"):
                    status.set(payload)
                elif kind == "done":
                    running = False
                    last_audio = payload.get("edited_audio", payload["yangning_final.wav"])
                    source_audio.set(last_audio)
                    if payload.get("edited_srt"):
                        source_srt.set(payload["edited_srt"])
                    settings["last_audio"] = last_audio
                    save_json(SETTINGS, settings)
                    app.v["audio"].set(last_audio)
                    # Do not apply the audio tempo a second time in the host Studio.
                    if "speed" in app.v:
                        app.v["speed"].set("1.0")
                    if "trim" in app.v:
                        app.v["trim"].set(False)
                    if hasattr(app, "auto_cut"):
                        app.auto_cut.set(False)
                    status.set("已导出完整修正WAV；原文件已保留，请试听接缝与读音。" if payload.get("edited_audio") else "WAV音频已生成，可试听或导入杨宁工作室制作成片。")
                    submit.state(["!disabled"])
                    resume.state(["!disabled"])
                elif kind in ("adjusted", "adjust_error"):
                    running = False
                    submit.state(["!disabled"]);resume.state(["!disabled"])
                    if kind == "adjusted":
                        old_audio=last_audio
                        last_audio=payload
                        settings.setdefault("audio_adjustment_history",[]).append({"source":old_audio,"result":payload})
                        settings["last_audio"]=last_audio
                        source_audio.set(last_audio)
                        save_json(SETTINGS,settings)
                        app.v["audio"].set(last_audio)
                        if "speed" in app.v: app.v["speed"].set("1.0")
                        if "trim" in app.v: app.v["trim"].set(False)
                        if hasattr(app,"auto_cut"): app.auto_cut.set(False)
                        status.set("微调WAV已另存。原音频和停顿保留，可试听最近WAV。")
                    else:
                        status.set("音频微调未完成，原文件保留。")
                        messagebox.showerror("微调未完成",payload,parent=win)
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
    update_mode()
    win.after(150, poll)
