"""Local OCR and preview controls for up to three translated intro titles."""
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,colorchooser
from pathlib import Path

PREFIXES=('opening_title','opening_topic','opening_text_3')
LABELS=('文字 1','文字 2','文字 3')

class OpeningTextDialog:
    def __init__(self,panel):
        self.panel=panel;self.app=panel.app;self.rows=[]
        if self.app.v['language'].get()=='ja':
            # Migrate the earlier Japanese defaults once, without resetting a
            # user's later font, size, position, or color choices on reopen.
            migrations=(('opening_title_size',64,110),('opening_title_size',96,110),
                ('opening_title_y',61,47),('opening_title_y',70,47),('opening_topic_size',64,120),
                ('opening_topic_size',72,120),('opening_topic_color','#101010','#000000'))
            for key,old,new in migrations:
                if str(panel.v[key].get()).strip().lower()==str(old).lower():panel.v[key].set(str(new))
            for key in ('opening_title_match_size','opening_topic_match_size'):
                if panel.v[key].get():panel.v[key].set(False)
            if panel.v['opening_topic_orientation'].get()=='horizontal':panel.v['opening_topic_orientation'].set('vertical')
        self.win=tk.Toplevel(self.app.root);self.win.title('片头中文文字识别与译文定位');self.win.geometry('1000x700')
        box=ttk.Frame(self.win,padding=14);box.pack(fill='both',expand=True)
        ttk.Label(box,text='在完整视频的片头范围识别中文。保留原中文，在横排文字下方或竖排文字旁边叠加译文。时间按视频画面定位，不使用配音时长。',wraplength=960).pack(anchor='w',pady=(0,8))
        ttk.Label(box,text='识别范围：0 秒至片头结束时间；先完成“自动定位片头与配音分界”。识别结果是候选时间，预览后可手动微调。',wraplength=960).pack(anchor='w',pady=(0,8))
        body=ttk.Frame(box);body.pack(fill='both',expand=True)
        canvas=tk.Canvas(body,highlightthickness=0);scroll=ttk.Scrollbar(body,orient='vertical',command=canvas.yview);inner=ttk.Frame(canvas)
        inner.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0,0),window=inner,anchor='nw');canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        for index,(prefix,label) in enumerate(zip(PREFIXES,LABELS)):
            frame=ttk.LabelFrame(inner,text=label,padding=8);frame.pack(fill='x',pady=5)
            enabled=panel.v[prefix+'_enabled']
            ttk.Checkbutton(frame,text='加入译文',variable=enabled).grid(row=0,column=0,sticky='w',padx=4)
            ttk.Label(frame,text='画面中文（搜索词）').grid(row=0,column=1,sticky='w')
            original=tk.StringVar(value=panel.v[prefix+'_original'].get())
            ttk.Entry(frame,textvariable=original,width=20).grid(row=0,column=2,sticky='ew',padx=4)
            ttk.Label(frame,text='对应外语').grid(row=0,column=3,sticky='w')
            translation=tk.StringVar(value=panel.v[prefix+'_text'].get())
            ttk.Entry(frame,textvariable=translation,width=28).grid(row=0,column=4,sticky='ew',padx=4)
            ttk.Label(frame,text='方向').grid(row=0,column=5,sticky='w')
            orientation=tk.StringVar(value=panel.v[prefix+'_orientation'].get())
            ttk.Combobox(frame,textvariable=orientation,values=('横排','竖排'),state='readonly',width=7).grid(row=0,column=6,padx=4)
            orientation.trace_add('write',lambda *_args,v=orientation,k=prefix:panel.v[k+'_orientation'].set('vertical' if v.get()=='竖排' else 'horizontal'))
            ttk.Label(frame,text='显示时间（视频秒）').grid(row=1,column=0,sticky='w',padx=4,pady=5)
            start=tk.StringVar(value=panel.v[prefix+'_start'].get());end=tk.StringVar(value=panel.v[prefix+'_end'].get())
            ttk.Entry(frame,textvariable=start,width=10).grid(row=1,column=1,sticky='w')
            ttk.Label(frame,text='至').grid(row=1,column=2,sticky='e')
            ttk.Entry(frame,textvariable=end,width=10).grid(row=1,column=3,sticky='w')
            status=tk.StringVar(value='等待识别；可直接填写时间和译文。')
            ttk.Label(frame,textvariable=status,wraplength=420).grid(row=1,column=4,columnspan=2,sticky='w')
            ttk.Button(frame,text='识别出现 / 消失时间',command=lambda i=index:self.locate(i)).grid(row=1,column=6,padx=4)
            appearance=ttk.Frame(frame);appearance.grid(row=2,column=0,columnspan=7,sticky='ew',pady=(5,0))
            ttk.Label(appearance,text='字体').pack(side='left',padx=(4,3))
            font_labels={'笔触体（Yuji Boku）':'Yuji Boku','明朝体（Noto Serif）':'Noto Serif CJK JP'}
            font_value=panel.v[prefix+'_font'].get()
            font=tk.StringVar(value=next((label for label,value in font_labels.items() if value==font_value),'笔触体（Yuji Boku）'))
            font_box=ttk.Combobox(appearance,textvariable=font,values=tuple(font_labels),state='readonly',width=20);font_box.pack(side='left',padx=(0,8))
            font.trace_add('write',lambda *_args,v=font,k=prefix,m=font_labels:panel.v[k+'_font'].set(m.get(v.get(),'Yuji Boku')))
            ttk.Label(appearance,text='字号').pack(side='left',padx=(0,3))
            size=tk.StringVar(value=panel.v[prefix+'_size'].get());ttk.Entry(appearance,textvariable=size,width=7).pack(side='left',padx=(0,8))
            size.trace_add('write',lambda *_args,v=size,k=prefix:panel.v[k+'_size'].set(v.get()))
            ttk.Label(appearance,text='颜色').pack(side='left',padx=(0,3))
            color=tk.StringVar(value=panel.v[prefix+'_color'].get());ttk.Entry(appearance,textvariable=color,width=10).pack(side='left')
            color.trace_add('write',lambda *_args,v=color,k=prefix:panel.v[k+'_color'].set(v.get()))
            def pick_color(v=color):
                _rgb,chosen=colorchooser.askcolor(color=v.get(),parent=self.win,title='选择译文字色')
                if chosen:v.set(chosen.upper())
            ttk.Button(appearance,text='选颜色',command=pick_color).pack(side='left',padx=(3,8))
            match=tk.BooleanVar(value=panel.v[prefix+'_match_size'].get())
            ttk.Checkbutton(appearance,text='匹配原字大小',variable=match,command=lambda v=match,k=prefix:panel.v[k+'_match_size'].set(v.get())).pack(side='left',padx=3)
            ttk.Button(appearance,text='预览译文效果',command=lambda i=index:self.preview(i)).pack(side='right',padx=4)
            frame.columnconfigure(4,weight=1)
            original.trace_add('write',lambda *_args,v=original,k=prefix:panel.v[k+'_original'].set(v.get()))
            translation.trace_add('write',lambda *_args,v=translation,k=prefix:panel.v[k+'_text'].set(v.get()))
            start.trace_add('write',lambda *_args,v=start,k=prefix:panel.v[k+'_start'].set(v.get()))
            end.trace_add('write',lambda *_args,v=end,k=prefix:panel.v[k+'_end'].set(v.get()))
            self.rows.append(dict(prefix=prefix,original=original,translation=translation,start=start,end=end,orientation=orientation,status=status,enabled=enabled,font=font,size=size,color=color,match=match))
        ttk.Label(box,text='日语默认采用已确认的样式；每项文字都可单独改字体、字号和颜色，也可勾选匹配原字大小。OCR 只辅助定位，无法把画面里烧录的字体完全复制出来。',wraplength=950).pack(anchor='w',pady=8)
        ttk.Button(box,text='完成',command=self.win.destroy).pack(anchor='e')
    def _scan_end(self):
        value=float(self.panel.v['combined_intro_end'].get() or 0)
        if value>0:return value
        from media import parse_srt
        from intro_boundary import cue_boundary
        from sequence_vnext import seconds
        source=self.app.v['video'].get();srt=self.app.v['source_srt'].get()
        if not source or not srt:raise ValueError('请先选择完整视频和视频时间轴 SRT。')
        refs=parse_srt(srt);return cue_boundary(refs,int(float(self.panel.v['combined_intro_last_cue'].get())),seconds(source,self.app.stop))[1]
    def _launch(self,kind,row,fn):
        if self.app.busy:messagebox.showinfo('正在处理','请等待当前任务完成或先停止。',parent=self.win);return
        row['status'].set('正在处理…')
        def work():
            try:value=fn()
            except Exception as e:self.app.events.put(('utility_dialog_event',self,'failed',(kind,row,str(e))));return
            self.app.events.put(('utility_dialog_event',self,kind,(row,value)))
        self.app.worker(work)
    def locate(self,index):
        row=self.rows[index];source=self.app.v['video'].get();target=row['original'].get().strip()
        if not source or not Path(source).is_file():messagebox.showerror('片头文字识别','请先选择完整视频。',parent=self.win);return
        if not target:messagebox.showerror('片头文字识别','请填写画面中的中文搜索词。',parent=self.win);return
        try:end=self._scan_end()
        except Exception as e:messagebox.showerror('片头文字识别',str(e),parent=self.win);return
        from opening_caption import detect
        prefix=row['prefix'];self._launch('located',row,lambda:detect(source,target,0,end,self.app.stop,self.app.progress,prefix))
    def preview(self,index):
        row=self.rows[index];prefix=row['prefix']
        try:
            self.panel.v[prefix+'_original'].set(row['original'].get());self.panel.v[prefix+'_text'].set(row['translation'].get())
            self.panel.v[prefix+'_start'].set(row['start'].get());self.panel.v[prefix+'_end'].set(row['end'].get())
            self.panel.v[prefix+'_orientation'].set('vertical' if row['orientation'].get()=='竖排' else 'horizontal')
            self.panel.v[prefix+'_enabled'].set(True)
            source=self.app.v['video'].get();settings=self.panel.value();language=self.app.v['language'].get()
            if not row['translation'].get().strip():raise ValueError('请先填写对应外语，再预览。')
            if not source or not Path(source).is_file():raise ValueError('请先选择完整视频。')
            output=self.panel.autosave.parent/'title_previews'
            from opening_caption_preview import render
            self._launch('preview',row,lambda:render(source,settings,language,prefix,output,self.app.stop,self.app.progress))
        except Exception as e:messagebox.showerror('片头译文预览',str(e),parent=self.win)
    def receive(self,kind,value):
        if not self.win.winfo_exists():return
        if kind=='failed':
            _kind,row,error=value;row['status'].set(error);messagebox.showwarning('片头文字处理失败',error,parent=self.win);return
        row,result=value
        if kind=='located':
            for key,var in (('start',row['start']),('end',row['end'])):var.set(f'{result[row["prefix"]+"_"+key]:.3f}')
            prefix=row['prefix']
            for suffix in ('x','y','color','reference_height','reference_advance','orientation','match_size'):
                if prefix+'_'+suffix in result:
                    value=result[prefix+'_'+suffix]
                    # Japanese uses the saved size ratio/style from the user's
                    # sample instead of copying the larger Chinese glyph size.
                    if suffix=='match_size' and self.app.v['language'].get()=='ja':value=False
                    if suffix=='match_size':row['match'].set(bool(value))
                    self.panel.v[prefix+'_'+suffix].set(value if suffix=='match_size' else str(value))
            row['enabled'].set(True);row['status'].set('识别到「'+result.get('recognized','')+'」；请预览并检查时间、方向和位置。')
            if not row['translation'].get().strip():
                try:
                    from opening_caption import localized_title
                    row['translation'].set(localized_title('',self.app.v['language'].get(),row['original'].get()))
                except ValueError:pass
        elif kind=='preview':
            row['status'].set('预览已生成。');from app import open_path;open_path(result)

def show(panel):
    current=getattr(panel,'opening_text_dialog',None)
    if current and current.win.winfo_exists():current.win.lift();return
    panel.opening_text_dialog=OpeningTextDialog(panel)
