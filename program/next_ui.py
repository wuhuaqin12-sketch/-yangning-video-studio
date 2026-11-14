"""Integrated optional sequence controls. Existing batch/sound/style tools stay available."""
import json,os,tempfile,uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from project_vnext import defaults,normalize,save_project,load_project,preview_key

class SequencePanel:
    def __init__(self,app,parent):
        self.app=app;self.v={};self.layout_vars={};self.saved_timer=None;self.restoring=True
        self.repair_previews={};self.last_preview='';self.approved_preview='';self.separation_preview_token='';self.layout_styles={};self.pause_override=None
        self.enabled=tk.BooleanVar(value=False)
        self.box=ttk.LabelFrame(parent,text='③ 背景 / 封面 / 横竖版与片头片尾',padding=10);self.box.pack(fill='x',pady=6)
        ttk.Checkbutton(self.box,text='启用新版完整项目流程（关闭时沿用原版正文流程）',variable=self.enabled,command=self.update).pack(anchor='w')
        self.controls=ttk.Frame(self.box)
        self.mode=tk.StringVar(value='智能自动选择');self.v['output_mode']=tk.StringVar(value='auto')
        row=ttk.Frame(self.controls);row.pack(fill='x',pady=4)
        ttk.Label(row,text='输出比例').pack(side='left')
        cb=ttk.Combobox(row,textvariable=self.mode,state='readonly',values=('智能自动选择','只生成横版16:9','只生成竖版9:16','横版＋竖版'),width=22);cb.pack(side='left',padx=8)
        cb.bind('<<ComboboxSelected>>',self.change_mode)
        ttk.Label(row,text='自动只作推荐，保留完整内容；可手动覆盖').pack(side='left')
        p=defaults()
        for key,value in p.items():
            if key in ('output_mode','layouts'):continue
            cls=tk.BooleanVar if isinstance(value,bool) else tk.StringVar
            self.v[key]=cls(value=value)
        def file_row(parent,key,label):
            r=ttk.Frame(parent);r.pack(fill='x',pady=3)
            ttk.Label(r,text=label,width=22).pack(side='left');ttk.Entry(r,textvariable=self.v[key]).pack(side='left',fill='x',expand=True)
            ttk.Button(r,text='选择',command=lambda:self.pick(key)).pack(side='left',padx=4)
            return r
        file_row(self.controls,'background','背景图（可选）')
        self.cover_anchor=ttk.Frame(self.controls);self.cover_anchor.pack(fill='x')
        self.cover_single=file_row(self.controls,'cover','封面图（可选）')
        self.cover_l=file_row(self.controls,'cover_landscape','横版封面图16:9')
        self.cover_p=file_row(self.controls,'cover_portrait','竖版封面图9:16')
        row=ttk.Frame(self.controls);row.pack(fill='x',pady=4)
        for label,key,values in [('封面秒数','cover_seconds',('2','3','5')),('转场','cover_transition',('cut','dissolve')),('比例不符时','cover_fit',('ask','contain','crop'))]:
            ttk.Label(row,text=label).pack(side='left',padx=4);ttk.Combobox(row,textvariable=self.v[key],values=values,state='readonly',width=10).pack(side='left')
        ttk.Label(self.controls,text='cut直接切换；dissolve交叉淡化。ask提示；contain等比例留边；crop等比例裁切。封面静音，配音不提前。').pack(anchor='w')
        row=ttk.Frame(self.controls);row.pack(fill='x',pady=5)
        ttk.Checkbutton(row,text='启用片头',variable=self.v['intro_enabled'],command=self.update).pack(side='left')
        ttk.Checkbutton(row,text='启用片尾',variable=self.v['outro_enabled'],command=self.update).pack(side='left',padx=20)
        self.intro=ttk.LabelFrame(self.controls,text='片头（独立时间轴）',padding=6)
        file_row(self.intro,'intro_video','片头视频')
        row=ttk.Frame(self.intro);row.pack(fill='x')
        ttk.Radiobutton(row,text='保留片头全部原声',variable=self.v['intro_mode'],value='original',command=self.update).pack(side='left')
        ttk.Radiobutton(row,text='保留背景音乐，替换中文讲话',variable=self.v['intro_mode'],value='music_voice',command=self.update).pack(side='left',padx=12)
        ttk.Radiobutton(self.intro,text='使用导入的片头背景音乐（不加配音或SRT）',variable=self.v['intro_mode'],value='external_music',command=self.update).pack(anchor='w')
        self.intro_voice=ttk.Frame(self.intro)
        file_row(self.intro_voice,'intro_audio','提前准备的片头配音')
        file_row(self.intro_voice,'intro_srt','片头原画面SRT')
        file_row(self.intro_voice,'intro_target_srt','已对齐片头配音SRT（可空）')
        ttk.Checkbutton(self.intro_voice,text='此片头已去人声 / 纯背景音乐，已试听确认',variable=self.v['intro_clean_audio']).pack(anchor='w')
        row=ttk.Frame(self.intro_voice);row.pack(fill='x',pady=3)
        ttk.Label(row,text='背景声分离模型比较').pack(side='left');ttk.Combobox(row,textvariable=self.v['intro_separation_model'],values=('htdemucs_ft','htdemucs'),state='readonly',width=16).pack(side='left',padx=5)
        ttk.Label(row,text='候选比较，不保证更干净').pack(side='left')
        self.number(self.intro_voice,'intro_music_gain','片头音乐音量倍数（0–2，默认1）')
        ttk.Button(self.intro_voice,text='20秒背景声分离试听（实验）',command=self.separation_preview).pack(anchor='w',pady=3)
        ttk.Button(self.intro_voice,text='确认背景声试听，允许整段分离',command=self.approve_separation).pack(anchor='w',pady=3)
        ttk.Label(self.intro_voice,text='SRT仅用于定位现成配音，不生成声音。中文残留或音乐失真时不要勾选确认。').pack(anchor='w')
        self.outro=ttk.LabelFrame(self.controls,text='片尾：完整保留原视频和音乐，不需要SRT或配音',padding=6)
        file_row(self.outro,'outro_video','选择片尾视频')
        self.combined=ttk.LabelFrame(self.controls,text='已经合成一个完整MP4（可选）',padding=6);self.combined.pack(fill='x',pady=5)
        ttk.Checkbutton(self.combined,text='正文导入的是完整MP4；按明确边界保护片尾',variable=self.v['combined']).pack(anchor='w')
        for key,label in [('combined_intro_end','原视频片头结束秒（无独立处理填0）'),('combined_outro_start','原视频片尾开始秒（必填）'),('combined_audio_split','合并配音片头结束秒（有片头时填）')]:self.number(self.combined,key,label)
        self.layouts=ttk.Notebook(self.controls);self.layouts.pack(fill='x',pady=5)
        for mode,label in [('landscape','横版设置'),('portrait','竖版设置')]:
            frame=ttk.Frame(self.layouts,padding=6);self.layouts.add(frame,text=label)
            variables={key:(tk.BooleanVar(value=value) if isinstance(value,bool) else tk.StringVar(value=value)) for key,value in p['layouts'][mode].items() if key!='style'};self.layout_vars[mode]=variables;self.layout_styles[mode]={}
            ttk.Checkbutton(frame,text='去除原视频已烧录中文字幕（与新字幕写入独立）',variable=variables['remove_chinese']).pack(anchor='w')
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
        self.number(self.controls,'preview_start','完整项目预览起点（秒）')
        self.number(self.controls,'preview_seconds','预览长度（默认15秒，最长60秒）')
        row=ttk.Frame(self.controls);row.pack(fill='x',pady=5)
        ttk.Button(row,text='生成完整项目范围预览',command=self.preview).pack(side='left')
        ttk.Button(row,text='确认预览，允许导出',command=self.approve_preview).pack(side='left',padx=6)
        ttk.Button(row,text='保存项目',command=self.save_as).pack(side='left',padx=8)
        ttk.Button(row,text='打开项目',command=self.load).pack(side='left')
        ttk.Button(row,text='恢复到稳定版v12.11',command=self.recover).pack(side='right')
        self.autosave=Path(os.environ.get('YANGNING_DATA_ROOT') or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'YangNingStudio')/'last_project_next.json'
        for variable in [self.enabled,self.mode,*self.v.values(),*[v for d in self.layout_vars.values() for v in d.values()],*app.v.values()]:variable.trace_add('write',lambda *_:self.changed())
        self.update();app.root.after(1200,self.offer_recover)
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
        if p:self.v[key].set(p)
    def pick_clean(self,mode):
        p=filedialog.askopenfilename()
        if p:self.layout_vars[mode]['clean_video'].set(p)
    def change_mode(self,event=None):
        self.v['output_mode'].set(dict(zip(('智能自动选择','只生成横版16:9','只生成竖版9:16','横版＋竖版'),('auto','landscape','portrait','both')))[self.mode.get()]);self.update()
    def value(self):
        p={k:v.get() for k,v in self.v.items()};p['layouts']={m:{**{k:v.get() for k,v in d.items()},'style':self.layout_styles[m]} for m,d in self.layout_vars.items()}
        return normalize(p)
    def save_style(self,mode):
        self.layout_styles[mode]=dict(self.app.pending_style);self.changed()
        messagebox.showinfo('样式已分别保存','已为'+('横版' if mode=='landscape' else '竖版')+'保存当前标题和字幕样式。另一比例的样式保持不变。')
    def changed(self):
        if not self.restoring and self.v['background_audio'].get() and not self.enabled.get():
            self.enabled.set(True);self.update();return
        try:self.app.sequence_settings=self.value() if self.enabled.get() else {}
        except (ValueError,tk.TclError):return
        if self.restoring:return
        if self.saved_timer:self.app.root.after_cancel(self.saved_timer)
        self.saved_timer=self.app.root.after(1000,self.auto_save)
    def update(self):
        self.controls.pack(fill='x') if self.enabled.get() else self.controls.pack_forget()
        for row in (self.cover_single,self.cover_l,self.cover_p):row.pack_forget()
        for row in ((self.cover_l,self.cover_p) if self.v['output_mode'].get()=='both' else (self.cover_single,)):row.pack(fill='x',pady=3,before=self.cover_anchor)
        self.intro.pack(fill='x',pady=5,before=self.combined) if self.v['intro_enabled'].get() else self.intro.pack_forget()
        self.intro_voice.pack(fill='x') if self.v['intro_mode'].get()=='music_voice' else self.intro_voice.pack_forget()
        self.outro.pack(fill='x',pady=5,before=self.combined) if self.v['outro_enabled'].get() else self.outro.pack_forget()
        self.changed()
    def project(self):
        j={k:v.get() for k,v in self.app.v.items()};j.update(sequence=self.value(),publish_settings=self.app.pending_style,trim=self.app.auto_cut.get(),next_enabled=self.enabled.get())
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
            self.enabled.set(job.get('next_enabled',True));self.mode.set(dict(zip(('auto','landscape','portrait','both'),('智能自动选择','只生成横版16:9','只生成竖版9:16','横版＋竖版')))[self.v['output_mode'].get()]);self.update()
            if missing:messagebox.showwarning('素材需要重新选择','以下素材已移动或删除：\n'+'\n'.join(missing.values()))
        except Exception as e:messagebox.showerror('打开项目',str(e))
    def offer_recover(self):
        try:
            if self.autosave.exists() and messagebox.askyesno('恢复项目','发现上次自动保存的项目，是否恢复素材路径和设置？'):self.load(self.autosave)
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
