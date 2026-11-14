"""Body-first UI. Optional settings collapse without deleting their values."""
import json,os,tempfile,uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from project_vnext import defaults,normalize,save_project,load_project,preview_key

SEGMENT_MODES=('只做正文（默认）','另加片头 / 片尾','整片视频（已有片头片尾）')
class SequencePanel:
    def __init__(self,app,parent):
        self.app=app;self.v={};self.layout_vars={};self.saved_timer=None;self.restoring=True
        self.repair_previews={};self.last_preview='';self.approved_preview='';self.separation_preview_token='';self.layout_styles={};self.pause_override=None
        self.enabled=tk.BooleanVar(value=False)
        self.appearance_open=tk.BooleanVar(value=False);self.details_open=tk.BooleanVar(value=False)
        self.segment_mode=tk.StringVar(value=SEGMENT_MODES[0])
        self.box=ttk.LabelFrame(parent,text='② 可选设置',padding=8);self.box.pack(fill='x',pady=5)
        bar=ttk.Frame(self.box);bar.pack(fill='x')
        self.appearance_button=ttk.Button(bar,text='画面设置（背景 / 封面 / 比例）',command=self.toggle_appearance);self.appearance_button.pack(side='left')
        ttk.Label(bar,text='素材方式').pack(side='left',padx=(18,6))
        mode=ttk.Combobox(bar,textvariable=self.segment_mode,values=SEGMENT_MODES,state='readonly',width=27);mode.pack(side='left');mode.bind('<<ComboboxSelected>>',self.change_segments)
        self.controls=ttk.Frame(self.box,padding=(4,6))
        self.mode=tk.StringVar(value='智能自动选择');self.v['output_mode']=tk.StringVar(value='auto')
        row=ttk.Frame(self.controls);row.pack(fill='x',pady=4)
        ttk.Label(row,text='输出比例').pack(side='left')
        cb=ttk.Combobox(row,textvariable=self.mode,state='readonly',values=('智能自动选择','只生成横版16:9','只生成竖版9:16','横版＋竖版'),width=22);cb.pack(side='left',padx=8);cb.bind('<<ComboboxSelected>>',self.change_mode)
        ttk.Button(row,text='标题与字幕样式',command=app.publish).pack(side='left',padx=8)
        p=defaults()
        for key,value in p.items():
            if key in ('output_mode','layouts'):continue
            self.v[key]=(tk.BooleanVar if isinstance(value,bool) else tk.StringVar)(value=value)
        def file_row(parent,key,label):
            r=ttk.Frame(parent);r.pack(fill='x',pady=3)
            ttk.Label(r,text=label,width=22).pack(side='left');ttk.Entry(r,textvariable=self.v[key]).pack(side='left',fill='x',expand=True)
            ttk.Button(r,text='选择',command=lambda:self.pick(key)).pack(side='left',padx=4)
            return r
        file_row(self.controls,'background','背景图（可选）')
        self.cover_anchor=ttk.Frame(self.controls);self.cover_anchor.pack(fill='x')
        self.cover_single=file_row(self.controls,'cover','封面图（可选）')
        self.cover_l=file_row(self.controls,'cover_landscape','横版封面图16:9');self.cover_p=file_row(self.controls,'cover_portrait','竖版封面图9:16')
        self.cover_options=ttk.Frame(self.controls)
        row=ttk.Frame(self.cover_options);row.pack(fill='x',pady=4)
        for label,key,values in [('封面秒数','cover_seconds',('2','3','5')),('转场','cover_transition',('cut','dissolve')),('封面比例不符','cover_fit',('ask','contain','crop'))]:
            ttk.Label(row,text=label).pack(side='left',padx=4);ttk.Combobox(row,textvariable=self.v[key],values=values,state='readonly',width=10).pack(side='left')
        ttk.Label(self.cover_options,text='cut直接切换；dissolve交叉淡化。ask提示；contain等比例留边；crop裁切。').pack(anchor='w')
        ttk.Button(self.controls,text='字幕位置 / 原中文字幕处理 ▾',command=self.toggle_details).pack(anchor='w',pady=5)
        self.layout_details=ttk.Frame(self.controls)
        self.layouts=ttk.Notebook(self.layout_details);self.layouts.pack(fill='x',pady=4)
        for mode,label in [('landscape','横版设置'),('portrait','竖版设置')]:
            frame=ttk.Frame(self.layouts,padding=6);self.layouts.add(frame,text=label)
            variables={key:(tk.BooleanVar(value=value) if isinstance(value,bool) else tk.StringVar(value=value)) for key,value in p['layouts'][mode].items() if key!='style'};self.layout_vars[mode]=variables;self.layout_styles[mode]={}
            ttk.Checkbutton(frame,text='去除原视频已烧录中文字幕（独立开关）',variable=variables['remove_chinese']).pack(anchor='w')
            ttk.Checkbutton(frame,text='只对修复区域做3帧平滑，减少闪烁（可能出现拖影）',variable=variables['repair_temporal']).pack(anchor='w')
            row=ttk.Frame(frame);row.pack(fill='x',pady=3)
            ttk.Label(row,text='低资源修复区域 x,y,宽,高').pack(side='left');ttk.Entry(row,textvariable=variables['repair_roi'],width=24).pack(side='left',padx=5)
            ttk.Button(row,text='15秒修复预览',command=lambda m=mode:self.repair_preview(m)).pack(side='left')
            ttk.Button(row,text='确认此预览可用',command=lambda m=mode:self.approve_repair(m)).pack(side='left',padx=5)
            row=ttk.Frame(frame);row.pack(fill='x')
            ttk.Label(row,text='新字幕上下偏移（像素）').pack(side='left');ttk.Entry(row,textvariable=variables['subtitle_offset_y'],width=10).pack(side='left',padx=5)
            for key,label in [('title_y','标题上下位置（百分比，可空）'),('title_font_size','标题字号（像素，可空）'),('subtitle_font_size','新字幕字号（像素，可空）')]:
                row=ttk.Frame(frame);row.pack(fill='x');ttk.Label(row,text=label).pack(side='left');ttk.Entry(row,textvariable=variables[key],width=12).pack(side='left',padx=5)
            ttk.Button(frame,text='为此比例保存当前标题 / 字幕完整样式',command=lambda m=mode:self.save_style(m)).pack(anchor='w',pady=3)
            ttk.Label(frame,text='优先选择无字幕原片；低资源区域修复可能模糊/闪烁，不能保证恢复衣服和桌子细节。不是AI连续帧重建。',wraplength=850).pack(anchor='w')
            row=ttk.Frame(frame);row.pack(fill='x')
            ttk.Label(row,text='无字幕原片（可选）').pack(side='left');ttk.Entry(row,textvariable=variables['clean_video']).pack(side='left',fill='x',expand=True)
            ttk.Button(row,text='选择',command=lambda m=mode:self.pick_clean(m)).pack(side='left')
        self.segments=ttk.LabelFrame(self.box,text='片头 / 片尾（按需启用）',padding=6)
        self.segment_switch=ttk.Frame(self.segments)
        ttk.Checkbutton(self.segment_switch,text='添加片头',variable=self.v['intro_enabled'],command=self.update).pack(side='left')
        ttk.Checkbutton(self.segment_switch,text='添加片尾',variable=self.v['outro_enabled'],command=self.update).pack(side='left',padx=20)
        self.intro=ttk.LabelFrame(self.segments,text='片头',padding=6)
        file_row(self.intro,'intro_video','片头视频')
        row=ttk.Frame(self.intro);row.pack(fill='x')
        ttk.Radiobutton(row,text='完整保留原声',variable=self.v['intro_mode'],value='original',command=self.update).pack(side='left')
        ttk.Radiobutton(row,text='音乐＋现成配音',variable=self.v['intro_mode'],value='music_voice',command=self.update).pack(side='left',padx=12)
        ttk.Radiobutton(row,text='只用导入的背景音乐',variable=self.v['intro_mode'],value='external_music',command=self.update).pack(side='left')
        self.intro_voice=ttk.Frame(self.intro)
        file_row(self.intro_voice,'intro_audio','片头配音');file_row(self.intro_voice,'intro_srt','片头原画面SRT');file_row(self.intro_voice,'intro_target_srt','已对齐配音SRT（可空）')
        ttk.Checkbutton(self.intro_voice,text='片头视频本身已去人声 / 纯音乐',variable=self.v['intro_clean_audio']).pack(anchor='w')
        self.separation_details=ttk.Frame(self.intro_voice)
        self.separation_open=tk.BooleanVar(value=False)
        self.separation_switch=ttk.Checkbutton(self.intro_voice,text='展开本地人声分离实验',variable=self.separation_open,command=self.update)
        row=ttk.Frame(self.separation_details);row.pack(fill='x')
        ttk.Label(row,text='本地候选模型').pack(side='left');ttk.Combobox(row,textvariable=self.v['intro_separation_model'],values=('htdemucs_ft','htdemucs'),state='readonly',width=16).pack(side='left',padx=5)
        ttk.Button(self.separation_details,text='20秒分离试听（实验）',command=self.separation_preview).pack(anchor='w',pady=3)
        ttk.Button(self.separation_details,text='确认试听，允许整段分离',command=self.approve_separation).pack(anchor='w')
        self.outro=ttk.LabelFrame(self.segments,text='片尾：完整保留画面和音乐，无需配音或SRT',padding=6);file_row(self.outro,'outro_video','片尾视频')
        self.combined=ttk.LabelFrame(self.segments,text='完整视频范围',padding=6)
        ttk.Label(self.combined,text='完整视频、合并配音和合并SRT仍放在上方素材区；不再重复导入独立片尾。',wraplength=850).pack(anchor='w')
        for key,label in [('combined_intro_end','原视频片头结束秒（没有填0）'),('combined_outro_start','原视频片尾开始秒'),('combined_audio_split','合并配音中的片头结束秒')]:self.number(self.combined,key,label)
        self.music=ttk.LabelFrame(self.segments,text='片头音乐（可选）',padding=5)
        file_row(self.music,'background_audio','片头背景音乐（可选）')
        ttk.Label(self.music,text='导入已去人声的音乐，仅作用于片头。').pack(anchor='w')
        ttk.Button(self.music,text='音乐起点 / 音量 / 清除',command=self.background_audio_settings).pack(anchor='w')
        self.segment_anchor=ttk.Frame(self.segments);self.segment_anchor.pack(fill='x')
        self.preview_controls=ttk.Frame(self.box)
        ttk.Button(self.preview_controls,text='生成范围预览',command=self.preview).pack(side='left')
        ttk.Button(self.preview_controls,text='确认预览',command=self.approve_preview).pack(side='left',padx=6)
        ttk.Button(self.preview_controls,text='预览起点 / 时长',command=self.preview_range).pack(side='left')
        self.autosave=Path(os.environ.get('YANGNING_DATA_ROOT') or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'YangNingStudio')/'last_project_next.json'
        self.has_startup_autosave=self.autosave.exists()
        for variable in [self.enabled,self.mode,*self.v.values(),*[v for d in self.layout_vars.values() for v in d.values()],*app.v.values()]:variable.trace_add('write',lambda *_:self.changed())
        self.update();app.root.after(1200,self.offer_recover)
    def toggle_appearance(self):
        self.appearance_open.set(not self.appearance_open.get());self.update()
    def toggle_details(self):
        self.details_open.set(not self.details_open.get());self.update()
    def preview_range(self):
        win=tk.Toplevel(self.app.root);win.title('预览范围');box=ttk.Frame(win,padding=15);box.pack(fill='both',expand=True)
        self.number(box,'preview_start','从第几秒开始');self.number(box,'preview_seconds','预览秒数（1–60）')
        ttk.Button(box,text='完成',command=win.destroy).pack(anchor='e')
    def raw_value(self):
        p={k:v.get() for k,v in self.v.items()};p['layouts']={m:{**{k:v.get() for k,v in d.items()},'style':self.layout_styles[m]} for m,d in self.layout_vars.items()}
        return normalize(p)
    def custom_appearance(self):
        p=self.raw_value();base=defaults()
        keys=('output_mode','background','cover','cover_landscape','cover_portrait','cover_seconds','cover_transition','cover_fit','layouts')
        def same(value,default):
            if isinstance(default,dict):return set(value)==set(default) and all(same(value[k],default[k]) for k in default)
            if isinstance(default,(int,float)) and not isinstance(default,bool):
                try:return float(value)==float(default)
                except (TypeError,ValueError):return False
            return value==default
        return any(not same(p[k],base[k]) for k in keys)
    def change_segments(self,event=None):
        self.enabled.set(self.segment_mode.get()!=SEGMENT_MODES[0] or self.custom_appearance());self.update()
    def number(self,parent,key,label):
        row=ttk.Frame(parent);row.pack(fill='x',pady=3);ttk.Label(row,text=label).pack(side='left');ttk.Entry(row,textvariable=self.v[key],width=14).pack(side='left',padx=8)
    def pick_background_audio(self):
        path=filedialog.askopenfilename(filetypes=[('音频 / 已去人声片头','*.wav *.mp3 *.m4a *.flac *.mp4 *.mov'),('全部文件','*.*')])
        if path:
            self.v['background_audio'].set(path)
            if self.v['intro_mode'].get()=='original':self.v['intro_mode'].set('external_music')
            self.enabled.set(True);self.update()
    def background_audio_settings(self):
        win=tk.Toplevel(self.app.root);win.title('片头背景音乐与音量');win.geometry('680x270')
        box=ttk.Frame(win,padding=16);box.pack(fill='both',expand=True)
        ttk.Label(box,text='当前作用范围：片头。完整视频模式按“片头结束秒”确定范围。',wraplength=620).pack(anchor='w',pady=6)
        self.number(box,'background_audio_offset','从背景音乐文件第几秒开始')
        self.number(box,'intro_music_gain','背景音乐音量倍数（0–2）')
        ttk.Label(box,text='导入的是已去掉讲话的音乐，不是自动人声分离。\n只替换片头原声，可与片头日语配音混合；正文和片尾不加这条音乐。\n音乐过短会提示，不自动循环、加速或铺满整片。',wraplength=620).pack(anchor='w',pady=8)
        ttk.Button(box,text='清除背景音乐',command=lambda:self.v['background_audio'].set('')).pack(anchor='w')

    def pick(self,key):
        p=filedialog.askopenfilename()
        if p:self.v[key].set(p);self.enabled.set(True);self.update()
    def pick_clean(self,mode):
        p=filedialog.askopenfilename()
        if p:self.layout_vars[mode]['clean_video'].set(p)
    def change_mode(self,event=None):
        self.enabled.set(True);self.v['output_mode'].set(dict(zip(('智能自动选择','只生成横版16:9','只生成竖版9:16','横版＋竖版'),('auto','landscape','portrait','both')))[self.mode.get()]);self.update()
    def value(self):
        p=self.raw_value();mode=self.segment_mode.get()
        p['combined']=mode==SEGMENT_MODES[2]
        if mode!=SEGMENT_MODES[1]:p['intro_enabled']=False;p['outro_enabled']=False
        if mode==SEGMENT_MODES[0] or (mode==SEGMENT_MODES[1] and (not p['intro_enabled'] or p['intro_mode']=='original')):p['background_audio']=''
        return p
    def save_style(self,mode):
        self.layout_styles[mode]=dict(self.app.pending_style);self.changed()
        messagebox.showinfo('样式已分别保存','已为'+('横版' if mode=='landscape' else '竖版')+'保存当前标题和字幕样式。另一比例的样式保持不变。')
    def changed(self):
        if not self.restoring:
            try:
                if self.segment_mode.get()!=SEGMENT_MODES[0] or self.custom_appearance():self.enabled.set(True) if not self.enabled.get() else None
            except (ValueError,tk.TclError):pass
        try:self.app.sequence_settings=self.value() if self.enabled.get() else {}
        except (ValueError,tk.TclError):return
        if any(self.v[k].get() for k in ('cover','cover_landscape','cover_portrait')):self.cover_options.pack(fill='x',after=self.cover_anchor)
        else:self.cover_options.pack_forget()
        if self.enabled.get():self.preview_controls.pack(fill='x',pady=4)
        else:self.preview_controls.pack_forget()
        if self.restoring:return
        if self.saved_timer:self.app.root.after_cancel(self.saved_timer)
        self.saved_timer=self.app.root.after(1000,self.auto_save)
    def update(self):
        mode=self.segment_mode.get()
        for part in (self.controls,self.segments,self.preview_controls):part.pack_forget()
        if self.appearance_open.get():self.controls.pack(fill='x')
        self.layout_details.pack(fill='x') if self.details_open.get() else self.layout_details.pack_forget()
        for row in (self.cover_single,self.cover_l,self.cover_p):row.pack_forget()
        for row in ((self.cover_l,self.cover_p) if self.v['output_mode'].get()=='both' else (self.cover_single,)):row.pack(fill='x',pady=3,before=self.cover_anchor)
        self.cover_options.pack(fill='x',after=self.cover_anchor) if any(self.v[k].get() for k in ('cover','cover_landscape','cover_portrait')) else self.cover_options.pack_forget()
        if mode!=SEGMENT_MODES[0]:self.segments.pack(fill='x',pady=5)
        for part in (self.segment_switch,self.intro,self.outro,self.combined,self.music):part.pack_forget()
        if mode==SEGMENT_MODES[1]:self.segment_switch.pack(fill='x',before=self.segment_anchor)
        if mode==SEGMENT_MODES[1] and self.v['intro_enabled'].get():self.intro.pack(fill='x',pady=4,before=self.segment_anchor)
        self.intro_voice.pack(fill='x') if self.v['intro_mode'].get()=='music_voice' else self.intro_voice.pack_forget()
        use_separation=not self.v['background_audio'].get() and not self.v['intro_clean_audio'].get()
        self.separation_switch.pack(anchor='w') if use_separation else self.separation_switch.pack_forget()
        self.separation_details.pack(fill='x') if use_separation and self.separation_open.get() else self.separation_details.pack_forget()
        if mode==SEGMENT_MODES[2]:self.combined.pack(fill='x',pady=4,before=self.segment_anchor)
        if mode==SEGMENT_MODES[2] or (mode==SEGMENT_MODES[1] and self.v['intro_enabled'].get() and self.v['intro_mode'].get()!='original'):self.music.pack(fill='x',pady=4,before=self.segment_anchor)
        if mode==SEGMENT_MODES[1] and self.v['outro_enabled'].get():self.outro.pack(fill='x',pady=4,before=self.segment_anchor)
        if self.enabled.get():self.preview_controls.pack(fill='x',pady=4)
        if hasattr(self.app,'media_labels'):
            complete=mode==SEGMENT_MODES[2]
            for key,label in [('video','完整视频 MP4' if complete else '正文视频 MP4'),('audio','整片配音（可留空）' if complete else '正文配音（可留空）'),('source_srt','整片SRT（外语）' if complete else '正文SRT（外语）')]:self.app.media_labels[key].configure(text=label)
        self.appearance_button.configure(text='收起画面设置 ▴' if self.appearance_open.get() else '画面设置（背景 / 封面 / 比例）')
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
            for key,value in job.items():
                if key in self.app.v:self.app.v[key].set(value)
            self.app.auto_cut.set(job.get('trim',True))
            self.app.language_manual=True
            labels={'ja':'日语','en':'英语','fr':'法语','de':'德语','id':'印尼语','zh':'中文','ko':'韩语','es':'西班牙语','pt':'葡萄牙语','it':'意大利语'}
            self.app.language_name.set(labels.get(job.get('language'),'其他语言'))
            self.app.pending_style=job.get('publish_settings') or {}
            self.pause_override=job.get('_pause_override')
            for key,var in self.v.items():var.set(job['sequence'][key])
            for mode,d in self.layout_vars.items():
                for key,var in d.items():var.set(job['sequence']['layouts'][mode][key])
                self.layout_styles[mode]=dict(job['sequence']['layouts'][mode].get('style') or {})
            ui=job.get('ui_state') or {}
            derived=SEGMENT_MODES[2] if job['sequence']['combined'] else (SEGMENT_MODES[1] if job['sequence']['intro_enabled'] or job['sequence']['outro_enabled'] else SEGMENT_MODES[0])
            self.segment_mode.set(ui.get('segment_mode') if ui.get('segment_mode') in SEGMENT_MODES else derived)
            for k,value in ui.get('parts_preferences',{}).items():
                if k in ('intro_enabled','outro_enabled','background_audio'):self.v[k].set(value)
            self.appearance_open.set(ui.get('appearance_open',False));self.details_open.set(ui.get('details_open',False))
            self.enabled.set(job.get('next_enabled',True));self.mode.set(dict(zip(('auto','landscape','portrait','both'),('智能自动选择','只生成横版16:9','只生成竖版9:16','横版＋竖版')))[self.v['output_mode'].get()]);self.update()
            if missing:messagebox.showwarning('素材需要重新选择','以下素材已移动或删除：\n'+'\n'.join(missing.values()))
        except Exception as e:messagebox.showerror('打开项目',str(e))
        finally:self.restoring=False;self.changed()
    def offer_recover(self):
        try:
            if self.has_startup_autosave and self.autosave.exists() and messagebox.askyesno('恢复项目','发现上次自动保存的项目，是否恢复素材路径和设置？'):self.load(self.autosave)
        finally:self.restoring=False
    def preview(self):
        if self.app.busy:return
        try:
            self.enabled.set(True);self.changed();self.app.detect_language();j=self.app.settings();j['_sequence_preview']=True
            j.update(id=uuid.uuid4().hex,status='待处理');self.app.jobs.append(j);self.app.refresh();self.app.run_jobs([j],export=True)
        except Exception as e:messagebox.showerror('项目预览',str(e))
    def approve_preview(self):
        try:
            key=preview_key(self.app.settings())
            if key!=self.last_preview:raise ValueError('请先为当前素材和当前设置生成范围预览；更改封面、字幕或布局后需要重新预览。')
            if messagebox.askyesno('确认预览','确认已经看过当前预览，接受音乐、字幕、修复区域和转场效果后，允许导出完整视频？'):self.approved_preview=key
        except Exception as e:messagebox.showinfo('先预览',str(e))
    def ready(self):
        try:return self.approved_preview==preview_key(self.app.settings())
        except Exception:return False
    def repair_preview(self,mode):
        if self.app.busy:return
        try:
            from sequence_vnext import repair
            source=self.app.v['video'].get();layout={k:v.get() for k,v in self.layout_vars[mode].items()};layout['remove_chinese']=True
            folder=Path(self.app.v['output'].get())/('修复预览_'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
            start=float(self.v['preview_start'].get())
            def work():
                path=repair(source,layout,folder,self.app.stop,True,start,15)
                from sequence_vnext import repair_key
                token=repair_key(source,layout['repair_roi'],layout.get('repair_temporal',True))
                self.app.events.put(('repair_preview_ready',mode,token,path))
            self.app.worker(work)
        except Exception as e:messagebox.showerror('字幕修复预览',str(e))
    def approve_repair(self,mode):
        from sequence_vnext import repair_key
        try:
            token=repair_key(self.app.v['video'].get(),self.layout_vars[mode]['repair_roi'].get(),self.layout_vars[mode]['repair_temporal'].get())
            if self.repair_previews.get(mode)!=token:raise ValueError('请先为同一视频、同一区域生成15秒修复预览。')
            if messagebox.askyesno('确认预览质量','你是否已经看过同一素材、同一区域的修复预览，接受可能的模糊、残影和闪烁？'):
                self.layout_vars[mode]['repair_approved'].set(token)
        except Exception as e:messagebox.showerror('确认修复',str(e))
    def separation_preview(self):
        if self.app.busy:return
        try:
            from background_separation import preview
            combined=self.v['combined'].get()
            source=self.app.v['video'].get() if combined else self.v['intro_video'].get();folder=Path(self.app.v['output'].get())/('背景声试听_'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
            model=self.v['intro_separation_model'].get();start=float(self.v['preview_start'].get())
            head=float(self.v['combined_intro_end'].get()) if combined else 0
            if combined and not 0<=start<head:raise ValueError('完整视频的背景声试听范围必须在已指定的片头范围内。')
            def work():
                from project_vnext import file_digest
                if combined:
                    from background_separation import separate
                    path=separate(source,folder,self.app.stop,self.app.progress,model,limit=min(20,head-start),start=start)
                else:path=preview(source,folder,self.app.stop,self.app.progress,model,start)
                self.app.events.put(('separation_preview_ready',file_digest(source)+':'+model+(':intro_end='+str(head) if combined else ''),path))
            self.app.worker(work)
        except Exception as e:messagebox.showerror('背景声试听',str(e))
    def approve_separation(self):
        try:
            from project_vnext import file_digest
            combined=self.v['combined'].get();source=self.app.v['video'].get() if combined else self.v['intro_video'].get()
            token=file_digest(source)+':'+self.v['intro_separation_model'].get()+(':intro_end='+str(float(self.v['combined_intro_end'].get())) if combined else '')
            if token!=self.separation_preview_token:raise ValueError('请先为当前片头生成20秒背景声分离试听。')
            if messagebox.askyesno('确认分离质量','请确认已听过当前试听，接受中文残留、混响及音乐损伤程度。若不满意，请取消，不会修改原片。'):
                self.v['intro_separation_approved'].set(token)
        except Exception as e:messagebox.showinfo('先试听',str(e))
    def recover(self):
        if self.app.busy:return
        if not messagebox.askyesno('恢复稳定版','先备份本测试版设置，使用独立运行环境和干净配置启动原始v12.11。不会删除视频、音频、字幕、图片或导出文件。首次需要联网准备旧版依赖。继续？'):return
        def work():
            from recovery_ui_backend import restore_isolated
            path=restore_isolated(self.app.stop,self.app.progress)
            self.app.events.put(('publish_done',str(path)))
        self.app.worker(work)
