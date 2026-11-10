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
from voice_prosody import default_template, choose_template, TEMPLATE_MODES
from japanese_pronunciation import READINGS, parse_overrides, reading_plan
from voice_adjust import STYLE_OPTIONS, PRESETS, interpret_instruction, adjust_audio, validate_options

DATA = Path(os.environ.get("YANGNING_CLOUD_DATA_DIR", str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "YangNingStudio")))
SETTINGS = DATA / "kaggle_voice_settings.json"
KEYRING_SERVICE = os.environ.get("YANGNING_CLOUD_CREDENTIAL_SERVICE", "YangNingStudio-Kaggle")


def _load_settings():
    try:
        value = json.loads(SETTINGS.read_text(encoding="utf-8"))
        if not isinstance(value,dict): return {}
        for name in ("tempo_by_language","prosody_templates","template_modes","generation_by_language","japanese_pronunciation_overrides","drafts"):
            if not isinstance(value.get(name,{}),dict): value[name]={}
        for name in ("audio_history","audio_adjustment_history"):
            if not isinstance(value.get(name,[]),list): value[name]=[]
        value["generation_by_language"]={k:v for k,v in value.get("generation_by_language",{}).items() if isinstance(v,dict)}
        value["audio_history"]=[v for v in value.get("audio_history",[]) if isinstance(v,dict) and isinstance(v.get("result"),str)]
        for pref in value["generation_by_language"].values():
            if not isinstance(pref.get("styles",[]),list): pref["styles"]=[]
            pref["styles"]=[name for name in pref.get("styles",[]) if name in STYLE_OPTIONS]
        return value
    except (OSError, ValueError):
        return {}


def _vault():
    if os.name != "nt":
        raise RuntimeError("此工作室版本使用Windows凭据库保存令牌，请在Windows版本中配置。")
    from keyring.backends.Windows import WinVaultKeyring
    return WinVaultKeyring()


def _wrap_labels(parent,width):
    for child in parent.winfo_children():
        if isinstance(child,ttk.Label):
            try:
                if int(child.cget("wraplength"))>0: child.configure(wraplength=max(220,width-32))
            except (tk.TclError,ValueError): pass


def _fit_window(window, width, height):
    window.geometry(f"{min(width,max(600,window.winfo_screenwidth()-60))}x{min(height,max(460,window.winfo_screenheight()-100))}")


def _scroll_pane(parent):
    outer=ttk.Frame(parent)
    outer.pack(fill="both",expand=True)
    canvas=tk.Canvas(outer,highlightthickness=0)
    bar=ttk.Scrollbar(outer,orient="vertical",command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)
    bar.pack(side="right",fill="y");canvas.pack(side="left",fill="both",expand=True)
    pane=ttk.Frame(canvas,padding=10)
    item=canvas.create_window((0,0),window=pane,anchor="nw")
    pane.bind("<Configure>",lambda event:canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",lambda event:(canvas.itemconfigure(item,width=event.width),_wrap_labels(pane,event.width-20)))
    def wheel(event):
        canvas.yview_scroll(-1 if event.delta>0 or getattr(event,"num",0)==4 else 1,"units")
    # No bind_all: wheel over another window/text must retain its own scrolling.
    canvas.bind("<MouseWheel>",wheel)
    canvas.bind("<Button-4>",wheel);canvas.bind("<Button-5>",wheel)
    pane.bind("<MouseWheel>",wheel)
    return pane


def open_kaggle_voice(app, parent=None):
    previous = getattr(app, "_cloud_voice_window", None)
    if previous is not None:
        try:
            if previous.winfo_exists():
                previous.deiconify()
                previous.lift()
                return
        except tk.TclError:
            pass
    settings = _load_settings()
    try:
        pointer=json.loads((DATA/"kaggle_voice_jobs"/"latest_manifest.json").read_text(encoding="utf-8"))
        candidate=Path(pointer["path"])
        older=Path(settings.get("last_manifest", ""))
        if candidate.is_file() and (not older.is_file() or candidate.stat().st_mtime>=older.stat().st_mtime):
            settings["last_manifest"]=str(candidate)
    except (OSError,ValueError,KeyError,TypeError): pass
    if settings.get("speed_standard_version") != 2:
        settings["tempo_by_language"] = {name: 1.0 for name in PROFILES}
        settings["speed_standard_version"] = 2
        save_json(SETTINGS, settings)
    win = tk.Toplevel(app.root)
    app._cloud_voice_window = win
    win.title("免费云端语音克隆 · VoxCPM2")
    _fit_window(win, 850, 760)
    win.minsize(720, 480)
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
    canvas.bind("<Configure>", lambda e: (canvas.itemconfigure(item, width=e.width), _wrap_labels(box,e.width-28)))
    events = queue.Queue()
    running = False

    username = tk.StringVar(value=settings.get("username", ""))
    dataset = tk.StringVar(value=settings.get("reference_dataset", ""))
    saved_language = settings.get("language", "日语")
    language = tk.StringVar(value=saved_language if saved_language in PROFILES else "日语")
    tempo = tk.StringVar(value=str(settings.get("tempo_by_language", {}).get(language.get(), profile_for(language.get())["tempo"])))
    selected_template=settings.get("prosody_templates",{}).get(language.get(),default_template(language.get()))
    if selected_template and not Path(selected_template).is_file() and Path(selected_template).name in ("japanese.wav","english.wav"):
        selected_template=default_template(language.get())
    template=tk.StringVar(value=selected_template)
    # Preserve an existing custom manual path during migration; otherwise use auto.
    initial_template_mode=settings.get("template_modes",{}).get(language.get())
    if initial_template_mode not in TEMPLATE_MODES:
        initial_template_mode="手动指定" if selected_template and selected_template!=default_template(language.get()) else "自动选择"
    template_mode=tk.StringVar(value=initial_template_mode)
    template_status=tk.StringVar()
    template_display=tk.StringVar()
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
    status = tk.StringVar(value="准备就绪。音色和读音需听检确认。" if settings.get("username") and settings.get("reference_dataset") else "首次使用：点击右上方更多设置 → 连接与输出，安全保存本人连接信息。")
    last_audio = settings.get("last_audio", "")
    prefs=settings.get("generation_by_language",{}).get(language.get(),{})
    gain=tk.StringVar(value=str(prefs.get("gain_db",0)))
    denoise=tk.BooleanVar(value=prefs.get("denoise",True))
    style_vars={name:tk.BooleanVar(value=name in prefs.get("styles",[])) for name in STYLE_OPTIONS}
    preset=tk.StringVar(value="自定义" if prefs.get("styles") else "自然")
    active_language=language.get()
    previous_mode="generate"
    drafts=settings.get("drafts",{})
    mode_info=tk.StringVar(value="生成新音频 · 只需正文，无需视频")
    option_summary=tk.StringVar()
    previous_audio=settings.get("previous_audio","")
    more = tk.Toplevel(win)
    more.title("更多设置")
    _fit_window(more,820,720)
    more.withdraw()
    more.protocol("WM_DELETE_WINDOW", more.withdraw)
    tabs = ttk.Notebook(more)
    tabs.pack(fill="both", expand=True, padx=12, pady=12)
    pages=[ttk.Frame(tabs) for _ in range(4)]
    for pane,label in zip(pages,("连接与输出","生成设置","模板与读音","修改原音频")):
        tabs.add(pane,text=label)
    connection_tab,generation_tab,language_tab,edit_tab=[_scroll_pane(page) for page in pages]
    ttk.Button(more,text="保存当前语言设置",command=lambda: save_preferences()).pack(pady=(0,8))
    ttk.Button(box,text="更多设置 ⋯",command=lambda: (more.deiconify(), more.lift())).pack(anchor="e")

    ttk.Label(box, text="1626老师原声 · 自然停顿保留", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
    ttk.Label(box, text="语气模板只提供节奏提示，音色参考保持1626。生成后请试听确认。", wraplength=740).pack(anchor="w", pady=(4, 10))
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
    ttk.Label(line,text="语气").pack(side="left")
    preset_combo=ttk.Combobox(line,textvariable=preset,values=tuple(PRESETS),state="readonly",width=12)
    preset_combo.pack(side="left",padx=8)
    preset_combo.bind("<<ComboboxSelected>>",lambda event: apply_preset())
    ttk.Button(line,text="详细调节",command=lambda: open_generation()).pack(side="left")
    ttk.Label(box,textvariable=option_summary,wraplength=730).pack(anchor="w",pady=3)
    ttk.Label(box,textvariable=template_status,wraplength=730).pack(anchor="w",pady=3)
    ttk.Label(box,textvariable=mode_info,wraplength=730).pack(anchor="w",pady=3)
    ttk.Button(box,text="修改已有音频 / 全文重做",command=lambda: (more.deiconify(),tabs.select(pages[3]),more.lift())).pack(anchor="w",pady=3)
    ttk.Label(generation_tab,text="生成前调节：语气是模型提示，速度/音量/降噪是生成后的自动处理。",wraplength=680).pack(anchor="w",pady=6)
    style_grid=ttk.Frame(generation_tab);style_grid.pack(fill="x")
    for i,(name,var) in enumerate(style_vars.items()):
        ttk.Checkbutton(style_grid,text=name,variable=var,command=lambda: custom_style()).grid(row=i//3,column=i%3,sticky="w",padx=8,pady=6)
    audio_row=ttk.Frame(generation_tab);audio_row.pack(fill="x",pady=10)
    ttk.Label(audio_row,text="音量变化 dB").pack(side="left")
    ttk.Combobox(audio_row,textvariable=gain,values=("-6","-2","0","2","4"),width=8).pack(side="left",padx=8)
    ttk.Checkbutton(audio_row,text="轻度降噪（默认开）",variable=denoise).pack(side="left")
    ttk.Button(generation_tab,text="恢复1倍 / 自然语气 / 轻度降噪",command=lambda: reset_generation()).pack(anchor="w",pady=8)
    generation_command=tk.StringVar()
    ttk.Label(generation_tab,text="快捷指令（用逗号分隔；仅支持已列选项）",wraplength=680).pack(anchor="w",pady=6)
    ttk.Entry(generation_tab,textvariable=generation_command).pack(fill="x",pady=4)
    ttk.Button(generation_tab,text="识别并应用到生成设置",command=lambda: apply_generation_command()).pack(anchor="w",pady=6)
    ttk.Label(generation_tab,text="不改变1626音色参考；不强制抬高音调；停顿不会自动剪掉。模型语气提示的实际效果需试听。",wraplength=680).pack(anchor="w",pady=6)
    combo.bind("<<ComboboxSelected>>", lambda e: update_profile(True))
    template_row = ttk.LabelFrame(language_tab, text="语气参考（音色始终使用1626）", padding=8)
    template_row.pack(fill="x", pady=5)
    template_row.columnconfigure(0,weight=1)
    template_mode_combo=ttk.Combobox(template_row,textvariable=template_mode,values=TEMPLATE_MODES,state="readonly",width=24)
    template_mode_combo.grid(row=0,column=0,sticky="w",pady=4)
    template_mode_combo.bind("<<ComboboxSelected>>",lambda event: update_template_status())
    template_entry=ttk.Entry(template_row,textvariable=template)
    template_entry.grid(row=1,column=0,sticky="ew",pady=5)
    ttk.Button(template_row,text="选择模板",command=lambda: select_manual_template()).grid(row=1,column=1,padx=5)
    ttk.Label(template_row,textvariable=template_status,wraplength=650).grid(row=2,column=0,columnspan=2,sticky="w",pady=6)
    ttk.Label(language_tab,text="自动按已标记语言的本机模板匹配，优先本语言。法语、德语暂缺模板时沿用已确认的英语节奏摘要；粤语、印尼语缺模板时用各自自然语气预设。不会从网上随意抓取声音，也不自动识别素材语言。",wraplength=680).pack(anchor="w",pady=6)
    ttk.Label(box, text="输出WAV音频 · 普通生成只需正文，无需视频或原音频。", wraplength=740).pack(anchor="w", pady=6)
    choices = ttk.Frame(edit_tab)
    choices.pack(fill="x", pady=6)
    for label, value in (("生成新音频", "generate"), ("修改全文后重新生成", "full"), ("局部改读音并接回原音频", "partial")):
        ttk.Radiobutton(choices, text=label, variable=mode, value=value, command=lambda: update_mode()).pack(anchor="w",pady=4)
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
    script_frame=ttk.Frame(box);script_frame.pack(fill="both",expand=True,pady=(0,8))
    text_box = tk.Text(script_frame, height=10, wrap="word", undo=True)
    text_scroll=ttk.Scrollbar(script_frame,command=text_box.yview)
    text_box.configure(yscrollcommand=text_scroll.set)
    text_scroll.pack(side="right",fill="y");text_box.pack(side="left",fill="both",expand=True)
    text_box.insert("1.0",drafts.get("generate",""))
    count=tk.StringVar()
    ttk.Label(box,textvariable=count).pack(anchor="w")
    text_box.bind("<KeyRelease>",lambda event: update_count())
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
    ttk.Label(box, textvariable=status, wraplength=730).pack(anchor="w", pady=8)
    progressbar=ttk.Progressbar(box,mode="indeterminate")
    progressbar.pack(fill="x",pady=3)
    results_row=ttk.Frame(box);results_row.pack(fill="x",pady=4)
    ttk.Button(results_row,text="试听上一版",command=lambda: play_path(previous_audio)).pack(side="left")
    ttk.Button(results_row,text="版本与输出文件",command=lambda: result_history()).pack(side="left",padx=6)
    ttk.Button(connection_tab,text="查看最近任务日志",command=lambda: show_log()).pack(anchor="w",pady=8)
    ttk.Button(connection_tab,text="检查本机环境",command=lambda: local_check()).pack(anchor="w",pady=8)
    actions = ttk.Frame(box)
    actions.pack(fill="x", pady=5)
    preview = ttk.Button(actions, text="试听最近WAV", command=lambda: play_last())
    preview.pack(side="left")
    ttk.Button(actions,text="音频微调",command=lambda: adjustment_dialog()).pack(side="left",padx=6)
    resume = ttk.Button(actions, text="恢复最近任务", command=lambda: start(True))
    resume.pack(side="left", padx=8)
    submit = ttk.Button(box, text="生成音频", command=lambda: start(False))
    submit.pack(fill="x",pady=8)

    def options():
        return validate_options(tempo.get(),gain.get(),denoise.get(),[name for name,var in style_vars.items() if var.get()])

    def update_summary(*unused):
        try:
            opt=options()
            option_summary.set(f"{opt['tempo']:g}倍 · 音量{opt['gain_db']:+g}dB · 轻度降噪{'开' if opt['denoise'] else '关'} · "+("、".join(opt["styles"]) or "自然语气"))
        except ValueError as exc:
            option_summary.set("设置待修正："+str(exc))

    def apply_generation_command():
        try:
            result=interpret_instruction(generation_command.get())
            if result["unrecognized"]: raise ValueError("未识别："+"、".join(result["unrecognized"]))
            # Transactional: validate the merged result before changing any control.
            styles=list(dict.fromkeys([name for name,var in style_vars.items() if var.get()]+result["styles"]))
            validate_options(result["tempo"] if "tempo" in result["specified"] else tempo.get(),
                             result["gain_db"] if "gain_db" in result["specified"] else gain.get(),denoise.get(),styles)
            if "tempo" in result["specified"]: tempo.set(str(result["tempo"]))
            if "gain_db" in result["specified"]: gain.set(str(result["gain_db"]))
            if "denoise" in result["specified"]: denoise.set(result["denoise"])
            for name,var in style_vars.items(): var.set(name in styles)
            generation_command.set("");custom_style()
            status.set("生成设置已更新，请查看主页面参数摘要。")
        except ValueError as exc:
            messagebox.showinfo("指令未应用",str(exc),parent=more)

    def apply_preset():
        names=PRESETS.get(preset.get())
        if names is not None:
            for name,var in style_vars.items(): var.set(name in names)
        update_summary()

    def custom_style():
        preset.set("自定义");update_summary()

    def reset_generation():
        tempo.set("1.0");gain.set("0");denoise.set(True);preset.set("自然");apply_preset()

    def open_generation():
        more.deiconify();tabs.select(pages[1]);more.lift()

    def update_count():
        raw=text_box.get("1.0","end").strip()
        count.set(f"正文 {len(raw)} 字符 · 长文按完整语义段生成 · 日语读音稿可在更多设置预览")

    def update_mode():
        nonlocal previous_mode
        if previous_mode != mode.get():
            drafts[previous_mode]=text_box.get("1.0","end").strip()
            text_box.delete("1.0","end");text_box.insert("1.0",drafts.get(mode.get(),drafts.get("generate","") if mode.get()=="full" else ""))
            previous_mode=mode.get()
        if mode.get() == "partial":
            if not source_audio.get(): source_audio.set(last_audio)
            correction.pack(fill="x", pady=5)
            script_label.configure(text="修改后的句段正文")
            submit.configure(text="重生成句段并连接完整音频")
            mode_info.set("当前：局部修改 · 主页面只填替换句段；输出连接后的完整音频")
        else:
            correction.pack_forget()
            script_label.configure(text="修改后的完整正文" if mode.get() == "full" else "朗读正文")
            submit.configure(text="全文重新生成" if mode.get() == "full" else "生成音频")
            mode_info.set("当前：全文重做 · 旧版保留" if mode.get()=="full" else "生成新音频 · 只需正文，无需视频")
        update_count()

    def update_template_status():
        try:
            selection=choose_template(language.get(),template_mode.get(),template.get())
            template_status.set(selection["description"])
            template_display.set(selection["path"])
        except ValueError as exc:
            template_status.set(str(exc))
        manual=template_mode.get()=="手动指定"
        template_entry.configure(textvariable=template if manual else template_display,state="normal" if manual else "readonly")

    def select_manual_template():
        value=filedialog.askopenfilename(parent=more,filetypes=[("音频","*.wav *.mp3 *.m4a *.flac")])
        if value:
            template.set(value);template_mode.set("手动指定");update_template_status()

    def store_language(name):
        opt=options()
        settings.setdefault("tempo_by_language",{})[name]=opt["tempo"]
        settings.setdefault("prosody_templates",{})[name]=template.get()
        settings.setdefault("template_modes",{})[name]=template_mode.get()
        settings.setdefault("generation_by_language",{})[name]=opt

    def update_profile(reset=False):
        nonlocal active_language
        if reset:
            try:
                store_language(active_language)
            except ValueError as exc:
                language.set(active_language)
                messagebox.showerror("请先修正设置",str(exc),parent=win);return
            active_language=language.get()
            tempo.set(str(settings.get("tempo_by_language",{}).get(active_language,1.0)))
            template_value=settings.get("prosody_templates",{}).get(active_language,default_template(active_language))
            if template_value and not Path(template_value).is_file() and Path(template_value).name in ("japanese.wav","english.wav"):
                template_value=default_template(active_language)
            template.set(template_value)
            chosen_mode=settings.get("template_modes",{}).get(active_language)
            if chosen_mode not in TEMPLATE_MODES:
                chosen_mode="手动指定" if template_value and template_value!=default_template(active_language) else "自动选择"
            template_mode.set(chosen_mode)
            pref=settings.get("generation_by_language",{}).get(active_language,{})
            gain.set(str(pref.get("gain_db",0)));denoise.set(pref.get("denoise",True))
            for name,var in style_vars.items(): var.set(name in pref.get("styles",[]))
            preset.set(next((label for label,names in PRESETS.items() if names==pref.get("styles",[])),"自定义"))
        if language.get()=="日语": pronunciation_row.pack(fill="x",pady=4)
        else: pronunciation_row.pack_forget()
        update_summary();update_template_status()

    def remember():
        store_language(language.get())
        drafts[mode.get()]=text_box.get("1.0","end").strip()
        settings.update(username=username.get().strip(),reference_dataset=dataset.get().strip(),language=language.get(),
                        output_dir=output.get(),seed=seed.get(),drafts=drafts,
                        japanese_pronunciation_enabled=pronunciation_enabled.get(),japanese_pronunciation_overrides=japanese_readings)
        save_json(SETTINGS,settings)

    def save_preferences():
        try:
            remember();status.set("当前语言设置和正文草稿已保存。")
        except (ValueError,OSError) as exc:
            messagebox.showerror("设置未保存",str(exc),parent=more)

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
            settings.update(username=user,reference_dataset=dataset.get().strip())
            save_json(SETTINGS,settings)
            status.set("连接信息已保存。令牌已存入Windows凭据库；尚未验证云端GPU权限。")
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

    def set_running(value):
        nonlocal running
        running=value
        for button in (submit,resume): button.state(["disabled"] if value else ["!disabled"])
        if value: progressbar.start(12)
        else: progressbar.stop()

    def start(recover):
        if running: return
        try:
            if recover:
                record=settings.get("last_manifest","")
                if not record or not Path(record).is_file(): raise ValueError("还没有可恢复的任务。")
                manifest=Path(record)
                job=json.loads(manifest.read_text(encoding="utf-8"))
                user=job["username"]
            else:
                user=username.get().strip()
                if generation_command.get().strip():
                    raise ValueError("生成指令框有未应用内容，请先识别并应用，或清空。")
                opt=options()
                edit=None
                if mode.get()=="partial":
                    if not Path(source_audio.get()).is_file(): raise ValueError("局部修改需先选择原音频。")
                    edit={"kind":"audio","mode":"partial","audio":source_audio.get(),"srt":source_srt.get(),"start":float(range_start.get()),"end":float(range_end.get())}
                snapshot=dict(root=DATA/"kaggle_voice_jobs",username=user,dataset=dataset.get().strip(),
                              text=script_from_text(text_box.get("1.0","end")),language=language.get(),seed=int(seed.get()),
                              output_dir=output.get(),tempo=opt["tempo"],gain_db=opt["gain_db"],light_denoise=opt["denoise"],
                              edit=edit,prosody_template=template.get().strip() or None,template_mode=template_mode.get(),
                              pronunciation_enabled=pronunciation_enabled.get(),japanese_readings=dict(japanese_readings),style_options=opt["styles"])
                remember()
            if token.get().strip():
                raise ValueError("令牌输入框有未保存内容，请先点击安全保存连接。")
            secret=_vault().get_password(KEYRING_SERVICE,user)
            if not secret: raise ValueError("请先在更多设置为本人Kaggle用户名安全保存令牌。")
        except Exception as exc:
            messagebox.showerror("还不能提交",str(exc) if isinstance(exc,(ValueError,OSError)) else "请检查连接和最近任务记录。",parent=win);return
        set_running(True)
        status.set("正在恢复已有任务，不重复提交…" if recover else "正在检查正文、模板与修改范围…")
        def work():
            try:
                record=manifest if recover else prepare_job(**snapshot)
                if not recover: events.put(("manifest",str(record)))
                run_job(record,secret,events.put,audio_only=True)
            except Exception as exc:
                events.put(("error",str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def adjustment_dialog():
        popup=tk.Toplevel(win);popup.title("音频微调 · 保留原版");_fit_window(popup,760,650)
        area=_scroll_pane(popup)
        selected_audio=tk.StringVar(value=last_audio)
        ttk.Label(area,text="普通音频微调 · 不需要云端GPU或克隆正文",font=("Microsoft YaHei UI",12,"bold")).pack(anchor="w",pady=6)
        row=ttk.Frame(area);row.pack(fill="x",pady=6)
        ttk.Entry(row,textvariable=selected_audio).pack(side="left",fill="x",expand=True)
        ttk.Button(row,text="选择音频",command=lambda: choose_media(selected_audio,[("音频","*.wav *.mp3 *.m4a *.flac")])).pack(side="left",padx=5)
        speed,volume=tk.StringVar(value="1.0"),tk.StringVar(value="0")
        noise=tk.BooleanVar(value=False)
        row=ttk.Frame(area);row.pack(fill="x",pady=8)
        ttk.Label(row,text="速度（保音高）").pack(side="left")
        ttk.Combobox(row,textvariable=speed,values=("0.75","0.9","1.0","1.1","1.25"),width=8).pack(side="left",padx=6)
        ttk.Label(row,text="音量变化 dB").pack(side="left")
        ttk.Combobox(row,textvariable=volume,values=("-6","-2","0","2","4"),width=8).pack(side="left",padx=6)
        ttk.Checkbutton(row,text="轻度降噪",variable=noise).pack(side="left")
        ttk.Label(area,text="快捷指令：放慢一点、加快一点、音量大一点、音量小一点、轻度降噪。用逗号分隔；识别后会显示实际数值。",wraplength=670).pack(anchor="w",pady=8)
        instructions=tk.StringVar();ttk.Entry(area,textvariable=instructions).pack(fill="x",pady=5)
        explanation=tk.StringVar(value="仅执行上方数值；未知或互相矛盾的指令会被拦下。")
        ttk.Label(area,textvariable=explanation,wraplength=670).pack(fill="x",pady=6)
        def parse():
            try:
                result=interpret_instruction(instructions.get())
                if result["unrecognized"]: raise ValueError("未识别："+"、".join(result["unrecognized"]))
                if result["styles"]:
                    raise ValueError("柔和、连贯等需要重新生成。请使用下面的生成前语气调节，不能在普通微调中直接实现。")
            except ValueError as exc:
                messagebox.showinfo("指令未应用",str(exc),parent=popup);return False
            if "tempo" in result["specified"]: speed.set(str(result["tempo"]))
            if "gain_db" in result["specified"]: volume.set(str(result["gain_db"]))
            if "denoise" in result["specified"]: noise.set(result["denoise"])
            instructions.set("")
            explanation.set(f"待执行：{speed.get()}倍、音量{volume.get()}dB、降噪{'开' if noise.get() else '关'}。")
            return True
        ttk.Button(area,text="识别指令并预览动作",command=parse).pack(anchor="w",pady=6)
        def local_apply():
            if running:
                messagebox.showinfo("任务进行中","请等待当前任务结束。",parent=popup);return
            if instructions.get().strip() and not parse(): return
            try:
                opt=validate_options(speed.get(),volume.get(),noise.get())
                source=selected_audio.get()
                if not Path(source).is_file(): raise ValueError("请选择有效音频。")
                if not output.get().strip(): raise ValueError("请在更多设置选择输出目录。")
            except ValueError as exc:
                messagebox.showerror("不能微调",str(exc),parent=popup);return
            target_dir=output.get()
            set_running(True);status.set("正在处理已有音频，保留原声道、原文件和停顿…")
            def work():
                try:
                    result=adjust_audio(source,target_dir,opt["tempo"],opt["gain_db"],opt["denoise"])
                    events.put(("adjusted",{"source":source,"result":result}))
                except Exception as exc: events.put(("adjust_error",str(exc)))
            threading.Thread(target=work,daemon=True).start();popup.destroy()
        ttk.Button(area,text="执行微调 → 另存新WAV",command=local_apply).pack(fill="x",pady=12)
        ttk.Separator(area).pack(fill="x",pady=12)
        ttk.Label(area,text="想改变柔和程度、连贯性或停顿方式？",font=("Microsoft YaHei UI",11,"bold")).pack(anchor="w")
        ttk.Label(area,text="请先在主页面提供对应的完整正文或待改句段，再调节语气重新生成。普通音频不会自动转录，也不会用滤镜假装改善说话方式。",wraplength=670).pack(anchor="w",pady=8)
        ttk.Button(area,text="打开生成前语气调节",command=lambda: (popup.destroy(),open_generation())).pack(anchor="w",pady=6)
        ttk.Label(area,text="不覆盖原版。双声道保留双声道；速度默认1.0倍；不改变音高或剪掉停顿。微调后不要沿用旧SRT时间轴直接替换。",wraplength=670).pack(anchor="w",pady=10)

    def play_path(path):
        if not path or not Path(path).is_file():
            messagebox.showinfo("没有可用音频","请先完成生成或选择已有版本。",parent=win);return
        try:
            if os.name=="nt": os.startfile(path)
            else: subprocess.Popen(["xdg-open",path])
        except OSError as exc:
            messagebox.showerror("无法打开播放器",str(exc),parent=win)

    def result_history():
        popup=tk.Toplevel(win);popup.title("版本与输出文件");_fit_window(popup,760,520)
        listing=tk.Listbox(popup,exportselection=False)
        listing.pack(fill="both",expand=True,padx=12,pady=12)
        records=list(reversed(settings.get("audio_history",[])))
        if not records and last_audio: records=[{"result":last_audio,"kind":"已有结果"}]
        for record in records: listing.insert("end",f"{record.get('kind','音频')}  {Path(record['result']).name}")
        def selected():
            ids=listing.curselection();return records[ids[0]]["result"] if ids else ""
        def folder():
            path=selected()
            if path: play_path(str(Path(path).parent))
        row=ttk.Frame(popup);row.pack(fill="x",padx=12,pady=8)
        ttk.Button(row,text="试听选中版",command=lambda: play_path(selected())).pack(side="left")
        ttk.Button(row,text="打开所在文件夹",command=folder).pack(side="left",padx=8)
        ttk.Label(popup,text="版本不会覆盖。微调记录保存在对应输出文件夹；所有版本仍待音色和读音听检。",wraplength=680).pack(pady=8)

    def show_log():
        record=settings.get("last_manifest","")
        if not record or not Path(record).is_file():
            messagebox.showinfo("没有任务记录","先提交一次任务。",parent=more);return
        folder=Path(record).parent
        job=json.loads(Path(record).read_text(encoding="utf-8"))
        content=f"状态：{job.get('status')}\n最近错误：{job.get('last_error','无')}\n"
        log=folder/"remote_error.log"
        if log.is_file(): content+="\n"+log.read_text(encoding="utf-8",errors="replace")[-30000:]
        popup=tk.Toplevel(win);popup.title("最近任务日志");_fit_window(popup,780,580)
        view=tk.Text(popup,wrap="word");view.pack(fill="both",expand=True,padx=10,pady=10)
        view.insert("1.0",content);view.configure(state="disabled")

    def local_check():
        if running: return
        def work():
            try:
                from cloud_voice_preview import ensure_media_tools
                from voice_clip_edit import command,tool
                ensure_media_tools()
                filters=command([tool("ffmpeg"),"-hide_banner","-filters"]).decode("utf-8",errors="replace")
                if not all(name in filters for name in ("afftdn","rubberband","alimiter")):
                    raise RuntimeError("FFmpeg缺少所需音频滤镜，请重新运行启动安装检查。")
                events.put(("check_done","本机FFmpeg与音频滤镜可用。该检查不代表Kaggle账号权限、GPU余量或云端网络可用。"))
            except Exception as exc: events.put(("check_done",str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def play_last():
        play_path(last_audio)

    def install_result(path,kind,source=None):
        nonlocal last_audio,previous_audio
        previous_audio=source or last_audio
        last_audio=path
        settings.update(last_audio=path,previous_audio=previous_audio)
        records=settings.setdefault("audio_history",[])
        if not any(record.get("result")==path for record in records):
            records.append({"result":path,"source":previous_audio,"kind":kind})
        source_audio.set(path)
        save_json(SETTINGS,settings)
        app.v["audio"].set(path)
        if "speed" in app.v: app.v["speed"].set("1.0")
        if "trim" in app.v: app.v["trim"].set(False)
        if hasattr(app,"auto_cut"): app.auto_cut.set(False)

    def poll():
        try:
            while True:
                kind,payload=events.get_nowait()
                if kind in ("status","warning"): status.set(payload)
                elif kind=="manifest":
                    settings["last_manifest"]=payload;save_json(SETTINGS,settings)
                elif kind=="done":
                    set_running(False)
                    path=payload.get("edited_audio",payload.get("yangning_final.wav"))
                    if not path: raise ValueError("生成记录没有音频路径。")
                    install_result(path,"局部修改" if payload.get("edited_audio") else "云端生成")
                    # Old SRT belongs to old audio; never silently reuse it after another result.
                    source_srt.set(payload.get("edited_srt",""))
                    status.set("已导出新WAV，原版保留。请试听音色、全文完整性、术语读音和接缝。")
                elif kind=="adjusted":
                    set_running(False);install_result(payload["result"],"普通音频微调",payload["source"])
                    source_srt.set("")
                    status.set("微调WAV已另存。原版与声道保留，未自动调整SRT。可试听上一版比较。")
                elif kind in ("error","adjust_error"):
                    set_running(False)
                    status.set("任务未完成，原文件与任务记录保留；查看更多设置中的日志确认原因。")
                    messagebox.showerror("云端任务未完成" if kind=="error" else "微调未完成",payload,parent=win)
                elif kind=="check_done": messagebox.showinfo("本机环境检查",payload,parent=more)
        except queue.Empty: pass
        except Exception as exc:
            set_running(False)
            status.set("结果处理遇到问题："+str(exc))
        if win.winfo_exists(): win.after(150,poll)

    def close_window():
        try: remember()
        except (ValueError,OSError): pass
        more.withdraw()
        # Keep event handling alive while work is in flight; reopening reuses it.
        if running: win.withdraw()
        else: win.destroy()
    win.protocol("WM_DELETE_WINDOW",close_window)
    for var in (tempo,gain,denoise): var.trace_add("write",update_summary)
    template.trace_add("write",lambda *args: update_template_status())
    update_profile();update_mode();update_summary()
    win.after(150,poll)
