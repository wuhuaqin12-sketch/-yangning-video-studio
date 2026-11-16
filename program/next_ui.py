"""Body-first UI. Optional settings collapse without deleting their values."""
import json,os,tempfile,uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from project_vnext import defaults,normalize,save_project,load_project

SEGMENT_MODES=('只做正文（默认）','片头＋正文＋片尾（按需添加）')

def choice_combo(parent,variable,labels,**options):
    """Chinese labels over stable saved values, including project reloads."""
    reverse={value:label for label,value in labels.items()}
    display=tk.StringVar(master=parent,value=reverse.get(variable.get(),variable.get()))
    box=ttk.Combobox(parent,textvariable=display,values=tuple(labels),state='readonly',**options)
    box.bind('<<ComboboxSelected>>',lambda e:variable.set(labels[display.get()]))
    token=variable.trace_add('write',lambda *_:display.set(reverse.get(variable.get(),variable.get())))
    def detach(event):
        try:variable.trace_remove('write',token)
        except tk.TclError:pass
    box.bind('<Destroy>',detach)
    box.display=display
    return box

class SequencePanel:
    def __init__(self,app,parent):
        self.app=app;self.v={};self.layout_vars={};self.saved_timer=None;self.restoring=True
        self.repair_previews={};self.last_preview='';self.approved_preview='';self.separation_preview_token='';self.layout_styles={};self.pause_override=None;self.region_status={}
        self.enabled=tk.BooleanVar(value=True)
        self.appearance_open=tk.BooleanVar(value=False);self.details_open=tk.BooleanVar(value=False)
        self.segment_mode=tk.StringVar(value=SEGMENT_MODES[0])
        self.box=ttk.LabelFrame(parent,text='② 选择成片',padding=12,style='Section.TLabelframe');self.box.pack(fill='x',pady=5)
        bar=ttk.Frame(self.box);bar.pack(fill='x')
        ttk.Label(app.material_mode_row,text='素材方式',width=18).pack(side='left')
        self.segment_mode_box=ttk.Combobox(app.material_mode_row,textvariable=self.segment_mode,values=SEGMENT_MODES,state='readonly',width=30)
        self.segment_mode_box.pack(side='left');self.segment_mode_box.bind('<<ComboboxSelected>>',self.change_segments)
        self.controls=ttk.Frame(self.box,padding=(4,6))
        self.mode=tk.StringVar(value='只生成竖版9:16');self.v['output_mode']=tk.StringVar(value='portrait')
        ttk.Label(bar,text='输出比例').pack(side='left')
        self.output_mode_box=ttk.Combobox(bar,textvariable=self.mode,state='readonly',values=('智能自动选择','只生成横版16:9','只生成竖版9:16','横版＋竖版'),width=22)
        self.output_mode_box.pack(side='left',padx=(8,16));self.output_mode_box.bind('<<ComboboxSelected>>',self.change_mode)
        self.appearance_button=ttk.Button(bar,text='背景 / 封面 / 字幕设置 ▾',command=self.toggle_appearance);self.appearance_button.pack(side='left')
        row=ttk.Frame(self.controls);row.pack(fill='x',pady=4)
        ttk.Button(row,text='更多文字样式',command=app.publish).pack(side='left')
        ttk.Button(row,text='竖版画面大小（高级）',command=self.picture_settings).pack(side='left',padx=8)
        ttk.Label(self.controls,text='横版：16:9等比完整显示，不加背景和标题。竖版：保留背景、标题及视频下方字幕。',wraplength=760).pack(anchor='w',pady=3)
        p=defaults()
        for key,value in p.items():
            if key in ('output_mode','layouts'):continue
            self.v[key]=(tk.BooleanVar if isinstance(value,bool) else tk.StringVar)(value=value)
        def file_row(parent,key,label):
            r=ttk.Frame(parent);r.pack(fill='x',pady=3)
            ttk.Label(r,text=label,width=22).pack(side='left');ttk.Entry(r,textvariable=self.v[key]).pack(side='left',fill='x',expand=True)
            ttk.Button(r,text='选择',command=lambda:self.pick(key)).pack(side='left',padx=4)
            clear=ttk.Button(r,text='清除',command=lambda:self.clear_asset(key))
            def refresh(*_):
                clear.pack(side='left') if self.v[key].get() else clear.pack_forget()
            self.v[key].trace_add('write',refresh);refresh()
            return r
        self.background_row=file_row(self.controls,'background','竖版背景图（可选）')
        self.cover_anchor=ttk.Frame(self.controls);self.cover_anchor.pack(fill='x')
        self.cover_single=file_row(self.controls,'cover','封面图（可选）')
        self.cover_l=file_row(self.controls,'cover_landscape','横版封面图16:9');self.cover_p=file_row(self.controls,'cover_portrait','竖版封面图9:16')
        self.cover_options=ttk.Frame(self.controls)
        row=ttk.Frame(self.cover_options);row.pack(fill='x',pady=4)
        self.cover_choices={}
        for label,key,values in [('封面秒数','cover_seconds',{'2秒':'2','3秒':'3','5秒':'5'}),('转场','cover_transition',{'直接切换':'cut','交叉淡化':'dissolve'}),('比例不符时','cover_fit',{'先提示':'ask','等比例留边':'contain','等比例裁切':'crop'})]:
            ttk.Label(row,text=label).pack(side='left',padx=4)
            box=choice_combo(row,self.v[key],values,width=12);box.pack(side='left');self.cover_choices[key]=box
        ttk.Label(self.cover_options,text='封面实际写入MP4开头；期间静音，配音和字幕从后续视频开始。').pack(anchor='w')
        self.layout_details=ttk.Frame(self.controls)
        self.layouts=ttk.Notebook(self.layout_details);self.layouts.pack(fill='x',pady=4)
        for mode,label in [('landscape','横版设置'),('portrait','竖版设置')]:
            frame=ttk.Frame(self.layouts,padding=6);self.layouts.add(frame,text=label)
            variables={key:(tk.BooleanVar(value=value) if isinstance(value,bool) else tk.StringVar(value=value)) for key,value in p['layouts'][mode].items() if key!='style'};self.layout_vars[mode]=variables;self.layout_styles[mode]={}
            self.add_typography(frame,mode)
            ttk.Checkbutton(frame,text='去除原视频已烧录中文字幕',variable=variables['remove_chinese']).pack(anchor='w')
            ttk.Label(frame,text='字幕字号与位置自动安排；长句向下换行，更多文字分屏。默认只清除中文字与描边。',wraplength=800).pack(anchor='w',pady=3)
            actions=ttk.Frame(frame);actions.pack(fill='x',pady=3)
            ttk.Button(actions,text='鼠标框选字幕行',command=lambda m=mode:self.pick_subtitle_region(m)).pack(side='left',padx=4)
            ttk.Button(actions,text='15秒修复预览（可选）',command=lambda m=mode:self.repair_preview(m)).pack(side='left')
            self.region_status[mode]=tk.StringVar(value='尚未选择原中文字幕行；需要去字幕时再框选。')
            ttk.Label(frame,textvariable=self.region_status[mode],wraplength=800).pack(anchor='w')
            row=ttk.Frame(frame);row.pack(fill='x')
            ttk.Label(row,text='无字幕原片（可选）').pack(side='left');ttk.Entry(row,textvariable=variables['clean_video']).pack(side='left',fill='x',expand=True)
            ttk.Button(row,text='选择',command=lambda m=mode:self.pick_clean(m)).pack(side='left')
        self.segments=ttk.LabelFrame(app.segment_host,text='视频分段设置',padding=6)
        self.segment_switch=ttk.Frame(self.segments)
        ttk.Checkbutton(self.segment_switch,text='添加片头',variable=self.v['intro_enabled'],command=self.update).pack(side='left')
        ttk.Checkbutton(self.segment_switch,text='添加片尾',variable=self.v['outro_enabled'],command=self.update).pack(side='left',padx=20)
        self.intro=ttk.LabelFrame(self.segments,text='片头',padding=6)
        file_row(self.intro,'intro_video','片头视频')
        self.intro_choice=tk.StringVar(value='original');self.music_only=tk.BooleanVar(value=False);self.intro_more_open=tk.BooleanVar(value=False)
        self.intro_more=ttk.Frame(self.intro)
        row=ttk.Frame(self.intro);row.pack(fill='x')
        ttk.Radiobutton(row,text='保留片头原声',variable=self.intro_choice,value='original',command=self.change_intro_sound).pack(side='left')
        ttk.Radiobutton(row,text='替换片头声音',variable=self.intro_choice,value='replace',command=self.change_intro_sound).pack(side='left',padx=12)

        self.intro_voice=ttk.Frame(self.intro)
        file_row(self.intro_voice,'intro_audio','外语配音');file_row(self.intro_voice,'intro_srt','片头SRT（原画面时间）')
        file_row(self.intro_more,'intro_target_srt','已对齐配音SRT（可空）')
        ttk.Checkbutton(self.intro_more,text='只替换音乐，不加配音',variable=self.music_only,command=self.change_intro_sound).pack(anchor='w')
        self.intro_more_button=ttk.Button(self.intro,text='更多片头设置 ▾',command=self.toggle_intro_more)
        ttk.Checkbutton(self.intro_more,text='片头视频本身已去人声 / 纯音乐',variable=self.v['intro_clean_audio']).pack(anchor='w')
        self.outro=ttk.LabelFrame(self.segments,text='片尾：完整保留画面和音乐，无需配音或SRT',padding=6);file_row(self.outro,'outro_video','片尾视频')
        from ui_assets import load_music
        self.music_preferences=Path(os.environ.get('YANGNING_DATA_ROOT') or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'YangNingStudio')
        self.v['background_audio'].set(load_music(self.music_preferences))
        self.music=ttk.LabelFrame(self.segments,text='片头音乐（可选）',padding=5)
        file_row(self.music,'background_audio','片头背景音乐（可选）')
        ttk.Label(self.music,text='固定片头音乐：选择后自动记住，仅用于片头；文件移动后请重选。').pack(anchor='w')
        ttk.Button(self.music,text='音乐起点 / 音量 / 清除',command=self.background_audio_settings).pack(anchor='w')
        self.segment_anchor=ttk.Frame(self.segments);self.segment_anchor.pack(fill='x')
        self.preview_controls=ttk.Frame(self.box)
        preview_buttons=ttk.Frame(self.preview_controls);preview_buttons.pack(fill='x')
        self.range_preview_button=ttk.Button(preview_buttons,text='生成范围预览',command=self.preview);self.range_preview_button.pack(side='left')
        ttk.Button(preview_buttons,text='预览起点 / 时长',command=self.preview_range).pack(side='left')
        ttk.Label(self.preview_controls,text='预览可选；准备好素材后直接点“一键生成视频”导出完整成片。',wraplength=850).pack(anchor='w',pady=3)
        self.autosave=Path(os.environ.get('YANGNING_DATA_ROOT') or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'YangNingStudio')/'last_project_next.json'
        self.has_startup_autosave=self.autosave.exists()
        if self.has_startup_autosave:
            try:
                previous=json.loads(self.autosave.read_text(encoding='utf-8-sig'))['job']
                if previous.get('sequence',{}).get('combined') or str(previous.get('ui_state',{}).get('segment_mode','')).startswith('整片'):
                    import shutil
                    backup=self.autosave.with_name('完整视频旧项目备份_'+uuid.uuid4().hex[:8]+'.json');shutil.copy2(self.autosave,backup)
                    self.has_startup_autosave=False
                    app.root.after(1500,lambda p=str(backup):app.log_line('旧完整视频项目已备份，未自动载入。请重新选择三段素材。备份：'+p))
            except (OSError,ValueError,KeyError,TypeError):pass
        for variable in [self.enabled,self.mode,*self.v.values(),*[v for d in self.layout_vars.values() for v in d.values()],*app.v.values()]:variable.trace_add('write',lambda *_:self.changed())
        self.update();app.root.after(1200,self.offer_recover)
    def add_typography(self,parent,mode):
        if not hasattr(self,'style_vars'):self.style_vars={};self.style_timer=None;self.style_restoring=False
        from publish_style import DEFAULTS
        row=ttk.Frame(parent);row.pack(fill='x',pady=5)
        for suffix,label in (('subtitle_font_size','字号'),('subtitle_offset_y','上下微调')):
            key=mode+'_'+suffix
            value=self.app.pending_style.get(key,self.app.pending_style.get(suffix,DEFAULTS[key]))
            v=tk.StringVar(value=str(value));self.style_vars[key]=v
            ttk.Label(row,text=label).pack(side='left',padx=(4,4));ttk.Entry(row,textvariable=v,width=8).pack(side='left',padx=(0,12))
            v.trace_add('write',lambda *_:self.style_changed())
        ttk.Label(parent,text='字号与位置分别保存；正数下移，负数上移。',wraplength=740).pack(anchor='w')
    def current_style(self):
        from publish_style import normalize_style
        return normalize_style({**self.app.pending_style,**{k:v.get() for k,v in self.style_vars.items()}})
    def style_changed(self):
        if self.style_restoring:return
        try:self.app.pending_style=self.current_style()
        except ValueError:return
        if self.style_timer:self.app.root.after_cancel(self.style_timer)
        self.style_timer=self.app.root.after(400,self.persist_style)
    def persist_style(self):
        self.style_timer=None
        from desktop_update import atomic_json
        from app import DATA
        atomic_json(DATA/'style_no_denoise.json',self.app.pending_style)
        self.changed()
    def sync_styles(self):
        from publish_style import DEFAULTS
        self.style_restoring=True
        try:
            for key,v in self.style_vars.items():v.set(str(self.app.pending_style.get(key,DEFAULTS[key])))
        finally:self.style_restoring=False
    def toggle_appearance(self):
        self.appearance_open.set(not self.appearance_open.get());self.update()
    def toggle_details(self):
        self.details_open.set(not self.details_open.get());self.update()
    def picture_settings(self):
        win=tk.Toplevel(self.app.root);win.title('竖版画面大小');box=ttk.Frame(win,padding=16);box.pack(fill='both',expand=True)
        values={}
        for key,label,default in [('video_width','最大宽度 %',100),('video_height','最大高度 %（原默认76）',76)]:
            row=ttk.Frame(box);row.pack(fill='x',pady=6);ttk.Label(row,text=label,width=26).pack(side='left')
            values[key]=tk.StringVar(value=str(self.app.pending_style.get(key,default)));ttk.Entry(row,textvariable=values[key],width=12).pack(side='left')
        ttk.Label(box,text='仅调整竖版。横版固定16:9等比完整显示，不加背景和标题；字幕不会缩小画面。',wraplength=450).pack(pady=8)
        def save():
            try:
                from publish_style import normalize_style
                style=dict(self.app.pending_style);style.update({k:v.get() for k,v in values.items()});style=normalize_style(style)
                self.app.pending_style=style;self.enabled.set(True);self.app.events.put(('style_saved',style));self.update();win.destroy()
            except Exception as e:messagebox.showerror('画面大小',str(e),parent=win)
        ttk.Button(box,text='保存',command=save).pack(anchor='e')
    def set_processing_busy(self,busy):
        for button in (self.range_preview_button,):
            try:
                if button.winfo_exists():button.state(['disabled'] if busy else ['!disabled'])
            except tk.TclError:pass
    def expand_subtitle_roi(self,mode):
        if self.app.busy:return
        try:
            source=self.app.v['video'].get();roi=self.layout_vars[mode]['repair_roi'].get()
            def work():
                from sequence_vnext import full_width_subtitle_roi
                value=full_width_subtitle_roi(source,roi,self.app.stop)
                self.app.events.put(('repair_roi_expanded',mode,value))
            self.app.worker(work)
        except Exception as e:messagebox.showerror('扩展字幕行',str(e))
    def preview_dialog(self):
        if self.app.busy:return
        win=tk.Toplevel(self.app.root);win.title('预览（可选）');box=ttk.Frame(win,padding=14);box.pack(fill='both',expand=True)
        self.number(box,'preview_start','从第几秒开始');self.number(box,'preview_seconds','预览时长（1–60秒）')
        def start():win.destroy();self.preview()
        ttk.Button(box,text='生成范围预览',command=start).pack(anchor='e',pady=8)
    def preview_range(self):
        win=tk.Toplevel(self.app.root);win.title('预览范围');box=ttk.Frame(win,padding=15);box.pack(fill='both',expand=True)
        self.number(box,'preview_start','从第几秒开始');self.number(box,'preview_seconds','预览秒数（1–60）')
        ttk.Button(box,text='完成',command=win.destroy).pack(anchor='e')
    def raw_value(self):
        p={k:v.get() for k,v in self.v.items()};p['layouts']={m:{**{k:v.get() for k,v in d.items()},'style':self.layout_styles[m]} for m,d in self.layout_vars.items()}
        # Retired complete-video settings never enter new jobs or autosaves.
        base=defaults()
        for key in p:
            if key=='combined' or key.startswith(('combined_','opening_title_','opening_topic_','disclaimer_')):p[key]=base[key]
        for mode,layout in p['layouts'].items():
            for key in ('auto_long_subtitles','repair_full_width','subtitle_offset_y','title_y','title_font_size','subtitle_font_size','style'):layout[key]=base['layouts'][mode][key]
        return normalize(p)
    def custom_appearance(self):
        p=self.raw_value();base=defaults()
        keys=('output_mode','background','cover','cover_landscape','cover_portrait','cover_seconds','cover_transition','cover_fit','layouts',*[k for k in p if k.startswith('opening_title_') or k.startswith('opening_topic_') or k.startswith('disclaimer_')])
        def same(value,default):
            if isinstance(default,dict):return set(value)==set(default) and all(same(value[k],default[k]) for k in default)
            if isinstance(default,(int,float)) and not isinstance(default,bool):
                try:return float(value)==float(default)
                except (TypeError,ValueError):return False
            return value==default
        return any(not same(p[k],base[k]) for k in keys)
    def change_segments(self,event=None):
        self.enabled.set(True);self.update()
    def number(self,parent,key,label):
        row=ttk.Frame(parent);row.pack(fill='x',pady=3);ttk.Label(row,text=label).pack(side='left');ttk.Entry(row,textvariable=self.v[key],width=14).pack(side='left',padx=8)
    def pick_background_audio(self):
        self.pick('background_audio')
    def change_intro_sound(self):
        self.v['intro_mode'].set('original' if self.intro_choice.get()=='original' else 'external_music' if self.music_only.get() else 'music_voice');self.update()
    def toggle_intro_more(self):
        self.intro_more_open.set(not self.intro_more_open.get());self.update()
    def clear_asset(self,key):
        self.v[key].set('')
        if key in ('cover_landscape','cover_portrait'):self.v['cover'].set('')
        if key=='background_audio':
            from ui_assets import remember_music
            remember_music(self.music_preferences,'')
        self.update()
    def background_audio_settings(self):
        win=tk.Toplevel(self.app.root);win.title('片头背景音乐与音量');win.geometry('680x270')
        box=ttk.Frame(win,padding=16);box.pack(fill='both',expand=True)
        ttk.Label(box,text='只用于单独导入的片头视频；正文和片尾不使用这条音乐。',wraplength=620).pack(anchor='w',pady=6)
        self.number(box,'background_audio_offset','从背景音乐文件第几秒开始')
        self.number(box,'intro_music_gain','背景音乐音量倍数（0–2）')
        ttk.Label(box,text='导入的是已去掉讲话的音乐，不是自动人声分离。\n只替换片头原声，可与片头日语配音混合；正文和片尾不加这条音乐。\n音乐过短会提示，不自动循环、加速或铺满整片。',wraplength=620).pack(anchor='w',pady=8)
        ttk.Button(box,text='清除背景音乐',command=lambda:self.clear_asset('background_audio')).pack(anchor='w')


    def pick(self,key):
        from ui_assets import filetypes,check_image,remember_music
        p=filedialog.askopenfilename(filetypes=filetypes(key))
        if not p:return
        try:
            if key in ('background','cover','cover_landscape','cover_portrait'):check_image(p,'背景或封面')
            if key=='background_audio':remember_music(self.music_preferences,p)
            self.v[key].set(p);self.enabled.set(True);self.update()
        except Exception as e:messagebox.showerror('素材类型',str(e),parent=self.app.root)
    def pick_subtitle_region(self,mode):
        from roi_picker import show
        show(self,mode)
    def pick_clean(self,mode):
        p=filedialog.askopenfilename()
        if p:self.layout_vars[mode]['clean_video'].set(p)
    def change_mode(self,event=None):
        self.enabled.set(True);self.v['output_mode'].set(dict(zip(('智能自动选择','只生成横版16:9','只生成竖版9:16','横版＋竖版'),('auto','landscape','portrait','both')))[self.mode.get()]);self.update()
    def value(self):
        p=self.raw_value();mode=self.segment_mode.get()
        if mode!=SEGMENT_MODES[1]:p['intro_enabled']=False;p['outro_enabled']=False
        if not p['intro_enabled'] or p['intro_mode']=='original':p['background_audio']=''
        return p
    def changed(self):
        if not self.restoring:
            try:
                if self.segment_mode.get()!=SEGMENT_MODES[0] or self.custom_appearance():self.enabled.set(True) if not self.enabled.get() else None
            except (ValueError,tk.TclError):pass
        for mode,status in self.region_status.items():status.set('已选择字幕行；将自动横向扩满，只处理文字与描边。' if self.layout_vars[mode]['repair_roi'].get().strip() else '尚未选择原中文字幕行；需要去字幕时再框选。')
        try:self.app.sequence_settings=self.value() if self.enabled.get() else {}
        except (ValueError,tk.TclError):return
        if any(self.v[k].get() for k in ('cover','cover_landscape','cover_portrait')):self.cover_options.pack(fill='x',after=self.cover_anchor)
        else:self.cover_options.pack_forget()
        self.preview_controls.pack_forget()
        self.app.refresh_export_summary()
        if self.restoring:return
        if self.saved_timer:self.app.root.after_cancel(self.saved_timer)
        self.saved_timer=self.app.root.after(1000,self.auto_save)
    def update(self):
        mode=self.segment_mode.get()
        for part in (self.controls,self.segments,self.preview_controls):part.pack_forget()
        if self.appearance_open.get():self.controls.pack(fill='x')
        self.layout_details.pack(fill='x')
        for row in (self.cover_single,self.cover_l,self.cover_p):row.pack_forget()
        selected=self.v['output_mode'].get()
        self.background_row.pack(fill='x',before=self.cover_anchor) if selected!='landscape' else self.background_row.pack_forget()
        for row in ((self.cover_l,self.cover_p) if selected in ('both','auto') else (self.cover_l,) if selected=='landscape' else (self.cover_p,)):row.pack(fill='x',pady=3,before=self.cover_anchor)
        self.cover_options.pack(fill='x',after=self.cover_anchor) if any(self.v[k].get() for k in ('cover','cover_landscape','cover_portrait')) else self.cover_options.pack_forget()
        if mode!=SEGMENT_MODES[0]:self.segments.pack(fill='x',pady=5)
        for part in (self.segment_switch,self.intro,self.outro,self.music):part.pack_forget()
        if mode==SEGMENT_MODES[1]:self.segment_switch.pack(fill='x',before=self.segment_anchor)
        if mode==SEGMENT_MODES[1] and self.v['intro_enabled'].get():self.intro.pack(fill='x',pady=4,before=self.segment_anchor)
        self.intro_choice.set('original' if self.v['intro_mode'].get()=='original' else 'replace')
        self.music_only.set(self.v['intro_mode'].get()=='external_music')
        self.intro_voice.pack(fill='x') if self.v['intro_mode'].get()=='music_voice' else self.intro_voice.pack_forget()
        self.intro_more_button.pack_forget();self.intro_more.pack_forget()
        if self.v['intro_mode'].get()!='original':
            self.intro_more_button.pack(fill='x')
            if self.intro_more_open.get():self.intro_more.pack(fill='x')
        if mode==SEGMENT_MODES[1] and self.v['intro_enabled'].get() and self.v['intro_mode'].get()!='original':self.music.pack(fill='x',pady=4,before=self.segment_anchor)
        if mode==SEGMENT_MODES[1] and self.v['outro_enabled'].get():self.outro.pack(fill='x',pady=4,before=self.segment_anchor)
        self.preview_controls.pack_forget()
        if hasattr(self.app,'media_labels'):
            for key,label in [('video','正文视频 MP4'),('audio','正文配音（留空用原声）'),('source_srt','正文SRT（外语）')]:self.app.media_labels[key].configure(text=label)
        self.segments.configure(text='片头 / 片尾（按需启用）')
        selected=self.v['output_mode'].get()
        for idx,name in enumerate(('landscape','portrait')):
            self.layouts.tab(idx,state='normal' if selected in ('both','auto',name) else 'hidden')
        if selected in ('landscape','portrait'):self.layouts.select(0 if selected=='landscape' else 1)
        self.appearance_button.configure(text='收起背景 / 封面 / 字幕设置 ▴' if self.appearance_open.get() else '背景 / 封面 / 字幕设置 ▾')
        self.changed()
    def project(self):
        j={k:v.get() for k,v in self.app.v.items()};j.update(sequence=self.value(),ui_state={'segment_mode':self.segment_mode.get(),'appearance_open':self.appearance_open.get(),'details_open':self.details_open.get(),'parts_preferences':{k:self.v[k].get() for k in ('intro_enabled','outro_enabled','background_audio')}},publish_settings=self.app.pending_style,trim=self.app.auto_cut.get(),next_enabled=self.enabled.get())
        if self.pause_override is not None:j['_pause_override']=self.pause_override
        return j
    def auto_save(self):
        self.saved_timer=None
        try:save_project(self.autosave,self.project())
        except (ValueError,OSError,tk.TclError):pass
    def save_as(self):
        p=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('YangNing项目','*.json')])
        if p:
            try:save_project(p,self.project())
            except Exception as e:messagebox.showerror('保存项目',str(e))
    def load(self,path=None):
        if self.app.busy:return
        p=path or filedialog.askopenfilename(filetypes=[('YangNing项目','*.json')])
        if not p:return
        self.restoring=True
        try:
            job,missing=load_project(p)
            if job['sequence'].get('combined') or str(job.get('ui_state',{}).get('segment_mode','')).startswith('整片'):
                raise ValueError('此项目使用已撤下的完整视频切分模式，未载入。请分别选择片头、正文和片尾素材；原项目和素材均未改动。')
            for key,value in job.items():
                if key in self.app.v:self.app.v[key].set(value)
            self.app.auto_cut.set(job.get('trim',True))
            self.app.language_manual=True
            labels={'ja':'日语','en':'英语','fr':'法语','de':'德语','id':'印尼语','zh':'中文','yue':'粤语','ko':'韩语','es':'西班牙语','pt':'葡萄牙语','it':'意大利语'}
            self.app.language_name.set(labels.get(job.get('language'),'其他语言'))
            self.app.refresh_language_fields()
            self.app.pending_style=job.get('publish_settings') or {};self.sync_styles()
            self.pause_override=job.get('_pause_override')
            for key,var in self.v.items():var.set(job['sequence'][key])
            for mode,d in self.layout_vars.items():
                for key,var in d.items():var.set(job['sequence']['layouts'][mode][key])
                self.layout_styles[mode]=dict(job['sequence']['layouts'][mode].get('style') or {})
            if self.v['cover'].get():
                for ratio in ('landscape','portrait'):
                    if not self.v['cover_'+ratio].get():self.v['cover_'+ratio].set(self.v['cover'].get())
                self.v['cover'].set('')
            ui=job.get('ui_state') or {}
            derived=SEGMENT_MODES[1] if job['sequence']['intro_enabled'] or job['sequence']['outro_enabled'] else SEGMENT_MODES[0]
            saved_mode=ui.get('segment_mode')
            self.segment_mode.set(saved_mode if saved_mode in SEGMENT_MODES else derived)
            for k,value in ui.get('parts_preferences',{}).items():
                if k in ('intro_enabled','outro_enabled','background_audio'):self.v[k].set(value)
            self.appearance_open.set(ui.get('appearance_open',False));self.details_open.set(ui.get('details_open',False))
            self.enabled.set(True);self.mode.set(dict(zip(('auto','landscape','portrait','both'),('智能自动选择','只生成横版16:9','只生成竖版9:16','横版＋竖版')))[self.v['output_mode'].get()]);self.update()
            if missing:messagebox.showwarning('素材需要重新选择','以下素材已移动或删除：\n'+'\n'.join(missing.values()))
        except Exception as e:messagebox.showerror('打开项目',str(e))
        finally:self.restoring=False;self.changed()
    def offer_recover(self):
        try:
            if self.has_startup_autosave and self.autosave.exists() and messagebox.askyesno('恢复项目','发现上次自动保存的项目，是否恢复素材路径和设置？'):self.load(self.autosave)
        finally:self.restoring=False
    def preview(self):
        if self.app.busy:
            messagebox.showinfo('正在处理','当前任务尚未结束，请查看运行记录，等待或先停止。',parent=self.app.root);return
        try:
            self.enabled.set(True);self.changed();p=self.value()
            self.app.detect_language();j=self.app.settings();j['_sequence_preview']=True
            self.app.set_activity(True)
            j.update(id=uuid.uuid4().hex,status='待处理');self.app.jobs.append(j);self.app.refresh();self.app.run_jobs([j],export=True)
        except Exception as e:messagebox.showerror('项目预览',str(e),parent=self.app.root)
    def repair_preview(self,mode):
        if self.app.busy:return
        try:
            from sequence_vnext import repair
            source=self.app.v['video'].get();layout={k:v.get() for k,v in self.layout_vars[mode].items()};layout['remove_chinese']=True
            folder=Path(self.app.v['output'].get())/('修复预览_'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
            start=float(self.layout_vars[mode]['repair_preview_start'].get())
            def work():
                path=repair(source,layout,folder,self.app.stop,True,start,15,progress=self.app.progress)
                from sequence_vnext import layout_repair_key
                token=layout_repair_key(source,layout)
                self.app.events.put(('repair_preview_ready',mode,token,path))
            self.app.worker(work)
        except Exception as e:messagebox.showerror('字幕修复预览',str(e))
    def recover(self):
        if self.app.busy:return
        if not messagebox.askyesno('恢复稳定版','先备份当前版本设置，使用独立运行环境和干净配置启动原始v12.11。不会删除视频、音频、字幕、图片或导出文件。首次需要联网准备旧版依赖。继续？'):return
        def work():
            from recovery_ui_backend import restore_isolated
            path=restore_isolated(self.app.stop,self.app.progress)
            self.app.events.put(('publish_done',str(path)))
        self.app.worker(work)
