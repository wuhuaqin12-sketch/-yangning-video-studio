import os,json,threading,queue,uuid,subprocess,time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from engine import preview_audio,Cancelled,VERSION
from workflow import normalize,execute
from output_destination import preferred, remember, deliver
from audio_edit import import_plan,export_plan
DATA=Path(os.environ.get('YANGNING_DATA_ROOT') or Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'YangNingStudio')
DATA.mkdir(parents=True,exist_ok=True)
# Keep old queues intact; stale settings and analysis from old versions are not run.
STATE=DATA/'queue_noerase_v055.json'
def open_path(p):
    if os.name=='nt':os.startfile(str(p))
    else:subprocess.Popen(['xdg-open',str(p)])
class App:
    def __init__(self,root):
        self.root=root;root.title('杨宁视频工作室 · 成片制作 · '+VERSION)
        root.geometry(f'1000x{max(640,min(780,root.winfo_screenheight()-100))}');root.minsize(880,640)
        self.jobs=[];self.busy=False;self.stop=threading.Event();self.events=queue.Queue();self.started=0
        defaults=dict(video='',audio='',source_srt='',target_srt='',output=str(Path.home()/'Videos'/'YangNingOutputs'),name='',language='ja',speed='1.1',alignment='auto',audio_profile='off',audio_reference_srt='',font='',font_percent='5.6')
        defaults['output']=preferred(defaults['output'])
        self.v={k:tk.StringVar(value=v) for k,v in defaults.items()}
        self.sequence_settings={}
        self.auto_cut=tk.BooleanVar(value=True)
        self.v['audio_separate']=tk.BooleanVar(value=False)
        try:
            sound=json.loads((DATA/'sound_preferences.json').read_text(encoding='utf8'))
            if sound.get('audio_profile') in ('off','v11','v11_deep'):self.v['audio_profile'].set(sound['audio_profile'])
            self.v['audio_separate'].set(sound.get('audio_separate') is True)
        except (OSError,ValueError):pass
        try:self.pending_style=json.loads((DATA/'style_no_denoise.json').read_text(encoding='utf8'))
        except (OSError,ValueError):self.pending_style={}
        for k,value in dict(trim=True,mute=False,denoise=False,separate=False,burn=False).items():self.v[k]=tk.BooleanVar(value=value)
        try:
            saved=json.loads(STATE.read_text(encoding='utf8'))
            if isinstance(saved,list):
                for j in saved:
                    if not isinstance(j,dict) or not j.get('id'):continue
                    if j.get('status') not in ('失败','已停止','待处理','待导出','待试听') and not j.get('status','').startswith('完成'):j['status']='已停止';j['error']='上次运行中断，请重试。'
                    self.jobs.append(j)
        except (OSError,ValueError):pass
        outer=ttk.Frame(root);outer.pack(fill='both',expand=True)
        canvas=tk.Canvas(outer,highlightthickness=0);scroll=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        pane=ttk.Frame(canvas,padding=10);pane_id=canvas.create_window((0,0),window=pane,anchor='nw')
        pane.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(pane_id,width=e.width,height=max(pane.winfo_reqheight(),e.height)))
        heading=ttk.Frame(pane);heading.pack(fill='x',pady=(0,4))
        ttk.Label(heading,text='杨宁视频工作室',font=('Microsoft YaHei UI',20,'bold')).pack(side='left')
        ttk.Button(heading,text='更多 / 批量',command=self.advanced).pack(side='right')
        form=ttk.LabelFrame(pane,text='① 正文素材',padding=8);form.pack(fill='x',pady=6)
        self.media_labels={}
        for i,(k,label) in enumerate([('video','正文视频 MP4'),('audio','正文配音（可留空）'),('source_srt','正文SRT（外语）')]):
            self.media_labels[k]=ttk.Label(form,text=label);self.media_labels[k].grid(row=i,column=0,sticky='w',padx=(0,10),pady=4)
            ttk.Entry(form,textvariable=self.v[k]).grid(row=i,column=1,sticky='ew')
            ttk.Button(form,text='选择',command=lambda key=k:self.pick(key)).grid(row=i,column=2,padx=(6,0))
        form.columnconfigure(1,weight=1)
        ttk.Checkbutton(form,text='把新字幕写入视频画面',variable=self.v['burn']).grid(row=3,column=0,columnspan=3,sticky='w',pady=5)
        from next_ui import SequencePanel
        self.sequence_panel=SequencePanel(self,pane)
        self.target_label=ttk.Label(form,text='独立配音 SRT')
        self.target_entry=ttk.Entry(form,textvariable=self.v['target_srt'])
        self.target_button=ttk.Button(form,text='选择',command=lambda:self.pick('target_srt'))
        self.target_label.grid(row=5,column=0,sticky='w');self.target_entry.grid(row=5,column=1,sticky='ew');self.target_button.grid(row=5,column=2)
        for widget in (self.target_label,self.target_entry,self.target_button):widget.grid_remove()
        self.language_name=tk.StringVar(value='自动识别')
        self.language_manual=False
        options=ttk.Frame(form);options.grid(row=4,column=0,columnspan=3,sticky='w',pady=4)
        ttk.Label(options,text='配音语言').pack(side='left')
        language=ttk.Combobox(options,textvariable=self.language_name,values=('自动识别','日语','英语','中文','法语','印尼语','德语','西班牙语','意大利语','韩语','葡萄牙语','其他语言'),state='readonly',width=12)
        language.pack(side='left',padx=(6,12));language.bind('<<ComboboxSelected>>',self.language_changed)
        ttk.Label(options,text='速度').pack(side='left')
        ttk.Combobox(options,textvariable=self.v['speed'],values=('0.75','0.9','1.0','1.1','1.2','1.25','1.5','2.0'),state='readonly',width=6).pack(side='left',padx=6)
        ttk.Button(options,text='声音 / 停顿设置',command=self.sound_settings).pack(side='left',padx=10)
        final=ttk.LabelFrame(pane,text='③ 生成视频',padding=8);final.pack(fill='x',pady=6)
        destination=ttk.Frame(final);destination.pack(fill='x',pady=(0,6))
        ttk.Label(destination,text='保存到').pack(side='left',padx=(0,8))
        ttk.Entry(destination,textvariable=self.v['output']).pack(side='left',fill='x',expand=True)
        ttk.Button(destination,text='选择文件夹',command=lambda:self.pick('output')).pack(side='left',padx=(6,0))
        line=ttk.Frame(final);line.pack(fill='x')
        self.main_button=ttk.Button(line,text='一键生成视频',command=self.one_click_simple)
        self.main_button.pack(side='left',ipadx=24,ipady=8)
        ttk.Button(line,text='停止',command=self.request_stop).pack(side='left',padx=12)
        ttk.Button(line,text='打开输出文件夹',command=self.open_result).pack(side='left')
        self.status=tk.StringVar(value='默认只做正文；需要片头片尾时，再更改素材方式。')
        ttk.Label(pane,textvariable=self.status,wraplength=900).pack(anchor='w',pady=(8,2))
        self.bar=ttk.Progressbar(pane,mode='indeterminate');self.bar.pack(fill='x',pady=(0,6))
        self.activity_header=ttk.Frame(pane);self.activity_header.pack(fill='x',pady=2)
        self.activity_open=False
        self.activity_button=ttk.Button(self.activity_header,text='任务与运行记录 ▾',command=self.set_activity);self.activity_button.pack(side='left')
        self.activity=ttk.Frame(pane)
        history=ttk.Notebook(self.activity);history.pack(fill='both',expand=True,pady=3)
        tasks=ttk.Frame(history);logs=ttk.Frame(history);history.add(tasks,text='任务');history.add(logs,text='运行记录')
        self.table=ttk.Treeview(tasks,columns=('name','status','detail'),show='headings',height=3)
        self.table.pack(fill='both',expand=True)
        for key,label,width in [('name','任务',210),('status','状态',135),('detail','当前步骤 / 失败原因',550)]:self.table.heading(key,text=label);self.table.column(key,width=width,minwidth=70)
        self.table.bind('<Double-1>',self.show_detail)
        self.log=tk.Text(logs,height=3,wrap='word');self.log.pack(fill='both',expand=True)
        from desktop_ui import DesktopUpdates
        self.desktop_updates=DesktopUpdates(self,pane,compact=True)
        self.build_menu()
        self.refresh();root.after(100,self.poll);root.after(1000,self.heartbeat);root.protocol('WM_DELETE_WINDOW',self.close)
    def set_activity(self,visible=None):
        self.activity_open=not self.activity_open if visible is None else bool(visible)
        if self.activity_open:self.activity.pack(after=self.activity_header,fill='both',expand=True,pady=3)
        else:self.activity.pack_forget()
        self.activity_button.configure(text='收起任务与运行记录 ▴' if self.activity_open else '任务与运行记录 ▾')
    def build_menu(self):
        menu=tk.Menu(self.root);self.root.configure(menu=menu)
        project=tk.Menu(menu,tearoff=False);menu.add_cascade(label='项目',menu=project)
        project.add_command(label='打开项目',command=self.sequence_panel.load);project.add_command(label='保存项目',command=self.sequence_panel.save_as)
        tools=tk.Menu(menu,tearoff=False);menu.add_cascade(label='工具',menu=tools)
        for label,command in [('声音处理',self.sound_settings),('停顿与速度',self.timing_settings),('标题与字幕样式',self.publish),('批量与高级设置',self.advanced)]:tools.add_command(label=label,command=command)
        help_menu=tk.Menu(menu,tearoff=False);menu.add_cascade(label='更新与恢复',menu=help_menu)
        help_menu.add_command(label='检查更新',command=lambda:self.desktop_updates.check(True));help_menu.add_command(label='更新设置',command=self.desktop_updates.settings)
        help_menu.add_command(label='恢复到稳定版v12.11',command=self.sequence_panel.recover)
    def review_current(self):
        if self.busy:return
        try:folder=Path(self.current(True)['analysis'])
        except Exception:messagebox.showinfo('先处理声音','请先在步骤2完成声音处理。');return
        if (folder/'clean_project.json').is_file():self.clean_review()
        else:self.full_sound_review()
    def timing_settings(self):
        if self.busy:return
        win=tk.Toplevel(self.root);win.title('停顿与速度');win.geometry('620x250')
        box=ttk.Frame(win,padding=18);box.pack(fill='both',expand=True)
        ttk.Checkbutton(box,text='剪短多余空白，保留自然停顿',variable=self.auto_cut).pack(anchor='w',pady=5)
        line=ttk.Frame(box);line.pack(fill='x',pady=8)
        ttk.Label(line,text='配音语言').pack(side='left')
        choices=('英语','日语','法语','德语','西班牙语','意大利语','韩语','葡萄牙语','中文','印尼语','其他语言')
        language=ttk.Combobox(line,textvariable=self.language_name,values=choices,state='readonly',width=12)
        language.pack(side='left',padx=8);language.bind('<<ComboboxSelected>>',self.language_changed)
        ttk.Label(box,text='整段去噪试听保持原速。配音成片所有语言默认1.1倍，可在主页面选择倍速，保持音调。',wraplength=570).pack(anchor='w',pady=8)
        ttk.Button(box,text='保存，返回制作',command=win.destroy).pack(anchor='e',pady=8)
    def finish_movie(self):
        if self.busy:return
        from production import same_material,finish
        job=self.current();values={k:v.get() for k,v in self.v.items()}
        folder=Path(job['analysis']) if job and job.get('analysis') else None
        try:reuse=folder is not None and same_material(folder,values)
        except Exception as e:messagebox.showinfo('工程无法读取',str(e));return
        if not reuse:self.clean_start();return
        style=dict(self.pending_style);automatic=self.auto_cut.get();ident=job['id']
        def work():
            try:
                self.events.put(('state',ident,'正在导出',{}))
                path=finish(folder,values,style,automatic,self.stop,self.progress)
                self.events.put(('state',ident,'完成·检查通过',dict(result=str(Path(path).parent),error='')))
                self.events.put(('publish_done',deliver(path, preferred(j.get('output') or self.v['output'].get()))))
            except Cancelled:self.events.put(('state',ident,'已停止',dict(error='用户停止了任务')))
            except Exception as e:self.events.put(('state',ident,'失败',dict(error=str(e))))
        self.worker(work)
    def clean_start(self):
        if self.busy:return
        from clean_project import prepare,load,save,export
        style=dict(self.pending_style)
        job={k:v.get() for k,v in self.v.items()}
        job.update(id=uuid.uuid4().hex,name=Path(job['video']).stem or '原声预览',status='待处理',clean_project=True,auto_cut=self.auto_cut.get(),trim=self.auto_cut.get())
        if not Path(job['video']).is_file():messagebox.showinfo('选择视频','请先选择有效的视频。');return
        self.jobs.append(job);self.refresh();self.table.selection_set(job['id'])
        def work():
            self.events.put(('state',job['id'],'准备预览',{}))
            try:
                if job.get('audio'):
                    result=execute({**job,'publish_settings':style},self.stop,self.events.put,export=True)
                    if result:self.events.put(('publish_done',str(Path(result)/'video.mp4')))
                    return
                folder=prepare(job,self.stop,self.progress,make_previews=False)
                if style:
                    meta=load(folder);meta['style']=style;save(Path(folder)/'clean_project.json',meta)
                self.events.put(('state',job['id'],'正在导出',dict(analysis=folder)))
                path=export(folder,self.stop,self.progress)
                self.events.put(('state',job['id'],'完成·检查通过',dict(analysis=folder,result=folder,error='')))
                self.events.put(('publish_done',path))
            except Cancelled:self.events.put(('state',job['id'],'已停止',dict(error='用户停止了任务')))
            except Exception as e:self.events.put(('state',job['id'],'失败',dict(error=str(e))))
        self.worker(work)
    def sound_settings(self):
        if self.busy:return
        win=tk.Toplevel(self.root);win.title('声音处理');win.geometry('720x700')
        box=ttk.Frame(win,padding=18);box.pack(fill='both',expand=True)
        ttk.Button(box,text='停顿与音画同步设置',command=self.timing_settings).pack(anchor='w',pady=4)
        ttk.Radiobutton(box,text='关闭降噪',variable=self.v['audio_profile'],value='off').pack(anchor='w',pady=4)
        ttk.Radiobutton(box,text='启用温和降噪（底噪、沙沙声、短促点击声）',variable=self.v['audio_profile'],value='v11').pack(anchor='w',pady=4)
        ttk.Radiobutton(box,text='V11 加强降噪（本次：RNNoise + 低频与点击声清理）',variable=self.v['audio_profile'],value='v11_deep').pack(anchor='w',pady=4)
        ttk.Label(box,text='对应这段音频的字幕 SRT（可选）').pack(anchor='w',pady=(8,2))
        refline=ttk.Frame(box);refline.pack(fill='x')
        ttk.Entry(refline,textvariable=self.v['audio_reference_srt']).pack(side='left',fill='x',expand=True)
        def choose_reference():
            path=filedialog.askopenfilename(parent=win,title='选择待降噪音频对应时间轴的字幕',filetypes=[('字幕 SRT','*.srt'),('带时间轴 TXT','*.txt')])
            if path:self.v['audio_reference_srt'].set(path)
        ttk.Button(refline,text='选择字幕',command=choose_reference).pack(side='right',padx=4)
        ttk.Label(box,text='仅用于声音报告按时间段附上字幕，不替换视频字幕；请选与待降噪音频匹配的时间轴。',wraplength=650).pack(anchor='w',pady=4)
        def v11_preset():
            self.v['audio_profile'].set('v11_deep');self.v['audio_separate'].set(True)
        ttk.Button(box,text='一键降噪并生成试听',command=lambda:(v11_preset(),listen())).pack(anchor='w',pady=6)
        ttk.Button(box,text='查看 / 复制本次去噪指令',command=self.sound_rules).pack(anchor='w',pady=4)
        ttk.Button(box,text='查看当前任务声音报告',command=self.sound_report).pack(anchor='w',pady=4)
        ttk.Checkbutton(box,text='分离人声与背景音乐（独立可选）',variable=self.v['audio_separate']).pack(anchor='w',pady=8)
        ttk.Label(box,text='人声分离首次需要联网下载较大运行环境和模型，仅支持 Python 3.10–3.12；以后在本机处理。',wraplength=570).pack(anchor='w',pady=4)
        ttk.Label(box,text='设置用于新任务。保留原文件和原声；不自动删词、不主动改变音调。杂声与人声重叠时可能残留或影响音质，请对比试听。',wraplength=570).pack(anchor='w',pady=4)
        def listen():
            if self.busy:return
            job={k:v.get() for k,v in self.v.items()}
            if not Path(job.get('video','')).is_file():messagebox.showinfo('选择视频','请先选择视频。',parent=win);return
            job.update(id=uuid.uuid4().hex,name=Path(job['video']).stem,clean_project=True,auto_cut=False,trim=False,status='待处理')
            self.jobs.append(job);self.refresh();self.table.selection_set(job['id']);win.destroy()
            def work():
                try:
                    if job.get('audio'):
                        folder=execute(job,self.stop,self.events.put,export=False)
                        if folder:
                            from full_listen import preview_full
                            preview_full(folder,self.stop,True);preview_full(folder,self.stop,False)
                            self.events.put(('sound_ready',False))
                    else:
                        from clean_project import prepare,preview,load
                        folder=prepare(job,self.stop,self.progress,make_previews=False)
                        if self.pending_style:
                            from clean_project import load,save
                            m=load(folder);m['style']=dict(self.pending_style);save(Path(folder)/'clean_project.json',m)
                        from full_listen import preview_full
                        preview_full(folder,self.stop,True);preview_full(folder,self.stop,False)
                        self.events.put(('state',job['id'],'待试听',dict(analysis=folder)))
                        self.events.put(('sound_ready',True))
                except Cancelled:self.events.put(('state',job['id'],'已停止',dict(error='用户停止了任务')))
                except Exception as e:self.events.put(('state',job['id'],'失败',dict(error=str(e))))
            self.worker(work)
        ttk.Button(box,text='生成原声 / 处理后试听',command=listen).pack(anchor='w',pady=10)
        def save_sound():
            (DATA/'sound_preferences.json').write_text(json.dumps({k:self.v[k].get() for k in ('audio_profile','audio_separate')}),encoding='utf8');win.destroy()
        ttk.Button(box,text='保存设置，返回制作',command=save_sound).pack(anchor='e')
    def full_sound_review(self):
        if self.busy:return
        try:folder=Path(self.current(True)['analysis'])
        except Exception:messagebox.showinfo('整段试听','请先完成声音处理。');return
        win=tk.Toplevel(self.root);win.title('整段去噪试听');win.geometry('650x240')
        box=ttk.Frame(win,padding=18);box.pack(fill='both',expand=True)
        ttk.Label(box,text='从头听到尾：原速去噪试听，未剪停顿。成片倍速另按制作设置执行。',wraplength=600).pack(anchor='w',pady=8)
        def play(original):
            if self.busy:return
            from full_listen import preview_full
            self.worker(lambda:self.events.put(('publish_done',preview_full(folder,self.stop,original))))
        for label,original in [('听整段原声',True),('听整段处理后',False)]:
            ttk.Button(box,text=label,command=lambda a=original:play(a)).pack(anchor='w',pady=5)
        ttk.Button(box,text='查看声音处理报告',command=self.sound_report).pack(anchor='w',pady=8)
    def sound_report(self):
        try:
            job=self.current(True);path=Path(job['analysis'])/'声音处理明细.txt'
            if not path.is_file():raise ValueError('请先用新版本分析或制作任务，再查看声音报告。')
            open_path(str(path))
        except Exception as e:messagebox.showinfo('声音报告',str(e))
    def sound_rules(self):
        from sound_rules import TITLE,RULES
        from tkinter.scrolledtext import ScrolledText
        win=tk.Toplevel(self.root);win.title(TITLE);win.geometry('760x640')
        text=ScrolledText(win,wrap='word',font=('Microsoft YaHei UI',11),padx=16,pady=16)
        text.pack(fill='both',expand=True);text.insert('1.0',RULES);text.configure(state='disabled')
        def copy():
            win.clipboard_clear();win.clipboard_append(RULES)
        ttk.Button(win,text='复制全部指令',command=copy).pack(pady=10)
    def clean_review(self):
        if self.busy:return
        try:j=self.current(True);folder=Path(j['analysis'])
        except Exception:messagebox.showinfo('选择任务','请先制作一次，并选中相应任务。');return
        if not (folder/'clean_project.json').exists():
            self.listen(True);return
        from clean_project import load,preview,edit,undo,export
        try:m=load(folder)
        except Exception as e:messagebox.showinfo('重新建工程',str(e));return
        win=tk.Toplevel(self.root);win.title('整段试听与片段修改');win.geometry('740x560')
        box=ttk.Frame(win,padding=18);box.pack(fill='both',expand=True)
        ttk.Label(box,text='先试听，再决定；范围使用原视频秒数。',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w')
        start=tk.StringVar(value=str(m.get('preview_start',0)));end=tk.StringVar(value=str(m.get('preview_end',15)))
        line=ttk.Frame(box);line.pack(fill='x',pady=12)
        for label,var in [('开始（秒）',start),('结束（秒）',end)]:
            ttk.Label(line,text=label).pack(side='left');ttk.Entry(line,textvariable=var,width=10).pack(side='left',padx=8)
        note=tk.StringVar(value='可先听整段；局部试听每次最多60秒。修改范围可精确输入到0.01秒。')
        ttk.Label(box,textvariable=note,wraplength=650).pack(anchor='w')
        history=tk.Text(box,height=7,wrap='word');history.pack(fill='both',expand=True,pady=10)
        def refresh():
            data=load(folder);history.delete('1.0','end')
            for e in data['edits']:history.insert('end',('静音' if e['kind']=='mute' else '剪掉')+f" {e['start']:.2f}—{e['end']:.2f} 秒\n")
            history.insert('1.0',f"已自动剪短{len(data.get('auto_edits',[]))}处长空白。\n")
            if not data['edits']:history.insert('end','还没有手动修改。原声始终保留。')
        refresh()
        def full_play(original):
            if self.busy:return
            from full_listen import preview_full
            self.worker(lambda:self.events.put(('publish_done',preview_full(folder,self.stop,original))))
        whole=ttk.Frame(box);whole.pack(fill='x',pady=4)
        ttk.Button(whole,text='听整段原声',command=lambda:full_play(True)).pack(side='left',padx=4)
        ttk.Button(whole,text='听整段处理后',command=lambda:full_play(False)).pack(side='left',padx=4)
        def action(kind):
            if self.busy:return
            try:a,b=float(start.get()),float(end.get())
            except ValueError:messagebox.showinfo('时间','开始与结束请填秒数。',parent=win);return
            def work():
                if kind in ('mute','cut'):edit(folder,a,b,kind,self.stop)
                elif kind in ('undo','reset'):undo(folder,self.stop,kind=='reset')
                if kind=='clip':path=export(folder,self.stop,self.progress,preview_range=(a,b))
                elif kind=='image':path=export(folder,self.stop,self.progress,preview_time=__import__('clean_project').mapped(a,load(folder).get('cuts',[])))
                else:
                    path=preview(folder,self.stop,a,b)
                    if kind=='A':path=str(folder/'试听_原声.m4a')
                self.events.put(('publish_done',path));self.events.put(('review_refresh',refresh,note))
            self.worker(work)
        line=ttk.Frame(box);line.pack(fill='x',pady=5)
        for label,kind in [('听原声','A'),('听处理后','B'),('预览视频','clip')]:ttk.Button(line,text=label,command=lambda k=kind:action(k)).pack(side='left',padx=4)
        line=ttk.Frame(box);line.pack(fill='x',pady=5)
        for label,kind in [('这段静音','mute'),('剪掉这段','cut'),('撤销上一步','undo'),('恢复所有手动修改','reset')]:ttk.Button(line,text=label,command=lambda k=kind:action(k)).pack(side='left',padx=4)
        ttk.Button(box,text='查看声音处理报告',command=lambda:open_path(str(folder/'声音处理明细.txt'))).pack(anchor='w',pady=4)
        ttk.Label(box,text='“静音”保留时长；“剪掉”同步缩短音画与字幕。多余词需人工试听确认。',wraplength=650).pack(anchor='w',pady=8)
    def final_export(self):
        if self.busy:return
        try:j=dict(self.current(True));folder=Path(j['analysis'])
        except Exception:messagebox.showinfo('选择任务','请选中已制作或已分析的任务，再重新导出。');return
        if j.get('sequence'):
            try:
                if not self.sequence_panel.ready():
                    messagebox.showinfo('先预览','请先生成当前完整项目范围预览并确认，再重新导出。');return
                j.update(sequence=self.sequence_panel.value(),publish_settings=dict(self.pending_style),burn=self.v['burn'].get())
                j.pop('_sequence_preview',None);self.run_jobs([j],export=True)
            except Exception as e:messagebox.showerror('重新导出',str(e))
            return
        def work():
            try:
                if (folder/'clean_project.json').exists():
                    from clean_project import export
                    path=export(folder,self.stop,self.progress)
                else:
                    from engine import render
                    render(folder,self.stop,self.progress);path=str(folder/'video.mp4')
                self.events.put(('state',j['id'],'完成·检查通过',dict(result=str(folder),error='')))
                self.events.put(('publish_done',path))
            except Exception as e:self.events.put(('state',j['id'],'失败',dict(error=str(e))))
        self.worker(work)
    def publish(self):
        from publish_ui import show
        try:show(self,open_path)
        except Exception as e:messagebox.showinfo('重新建工程',str(e))
    def language_changed(self,event=None):
        mapping={'英语':'en','日语':'ja','法语':'fr','德语':'de','西班牙语':'es','意大利语':'it','韩语':'ko','葡萄牙语':'pt','中文':'zh','印尼语':'id','其他语言':'other'}
        name=self.language_name.get()
        self.language_manual=name!='自动识别'
        if not self.language_manual:return
        lang=mapping[name]
        self.v['language'].set(lang)
        self.v['alignment'].set('timed' if lang=='other' else 'auto')
        self.v['target_srt'].set('')
        for widget in (self.target_label,self.target_entry,self.target_button):
            if lang!='other':widget.grid_remove()
            else:widget.grid()
    def pick(self,k):
        selected=filedialog.askdirectory() if k=='output' else filedialog.askopenfilename()
        if selected:
            self.v[k].set(remember(selected) if k=='output' else selected)
    def settings(self):
        j={k:v.get() for k,v in self.v.items()};j['publish_settings']=dict(self.pending_style);j['trim']=self.auto_cut.get();j.pop('preview_time',None)
        if self.sequence_settings:j['sequence']=self.sequence_settings
        if self.sequence_settings and self.sequence_panel.pause_override is not None:j['_pause_override']=self.sequence_panel.pause_override
        if not 1<=float(j['font_percent'])<=15:raise ValueError('字号应为1–15%')
        if not j['name']:j['name']=Path(j['video']).stem or 'video'
        return normalize(j)
    def save(self):
        tmp=STATE.with_suffix('.writing');tmp.write_text(json.dumps(self.jobs,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(STATE)
    def refresh(self):
        selected=self.table.selection();self.table.delete(*self.table.get_children())
        for j in self.jobs:self.table.insert('','end',iid=j['id'],values=(j.get('name','video'),j.get('status','待处理'),j.get('error') or j.get('step','')))
        self.table.selection_set([i for i in selected if self.table.exists(i)])
        self.save()
    def current(self,required=False):
        ids=self.table.selection();j=next((j for j in self.jobs if j['id'] in ids),None)
        if required and not j:raise ValueError('请先在列表中选中一个任务。')
        return j
    def add(self):
        if self.busy:return
        try:
            j=self.settings();j.update(id=uuid.uuid4().hex,status='待处理',step='已加入队列，点击“开始处理队列”执行',error='')
            self.jobs.append(j);self.refresh();self.table.selection_set(j['id']);return j
        except Exception as e:messagebox.showerror('检查素材',str(e))
    def one_click_simple(self):
        """Main-page workflow: use the existing proven alignment/render pipeline."""
        # Respect the user's subtitle checkbox in the one-click workflow.
        try:self.detect_language()
        except ValueError as e:messagebox.showerror('语言不一致',str(e));return
        if self.sequence_settings and not self.sequence_panel.ready():
            messagebox.showinfo('先预览再导出','将先生成当前项目的范围预览。看过后，点击“确认预览”，再生成完整视频。')
            self.sequence_panel.preview();return
        self.one_click()
    def detect_language(self):
        """Manual selection overrides filename hints; no false speech-recognition claims."""
        if self.language_manual:return
        import re
        hint=(Path(self.v['audio'].get()).stem+' '+Path(self.v['source_srt'].get()).stem).lower()
        patterns=[('ja',r'日语|日本語|japanese|nihongo'),('en',r'英语|英語|english'),('fr',r'法语|法語|french|français'),('id',r'印尼|indonesian|bahasa'),('zh',r'中文|汉语|漢語|chinese'),('ko',r'韩语|韓語|korean'),('de',r'德语|德語|german'),('es',r'西班牙|spanish'),('pt',r'葡萄牙|portuguese'),('it',r'意大利|italian')]
        matches={code for code,pattern in patterns if re.search(pattern,hint)}
        if len(matches)!=1:raise ValueError('无法可靠自动识别语言，请在主页面手动选择配音语言。')
        self.v['language'].set(next(iter(matches)))
        self.v['alignment'].set('auto')
        self.v['target_srt'].set('')
    def one_click(self):
        if self.busy:return
        j=self.add()
        if j:self.run_jobs([dict(j)],export=True)
    def run_jobs(self,jobs,export=True):
        if self.busy:return
        def go():
            for j in jobs:
                if self.stop.is_set():break
                execute(j,self.stop,self.events.put,export=export)
        self.worker(go)
    def worker(self,fn):
        if self.busy:return
        self.busy=True;self.started=time.monotonic();self.stop.clear();self.bar.start(15);self.main_button.state(['disabled'])
        self.status.set('已启动，正在检查素材…')
        def work():
            try:fn()
            except Exception as e:self.events.put(('error',str(e)))
            finally:self.events.put(('idle',))
        threading.Thread(target=work,daemon=True).start()
    def start(self):
        if self.busy:return
        todo=[dict(j) for j in self.jobs if not j.get('clean_project') and j.get('status') in ('待处理','待导出','失败','已停止')]
        if not todo:messagebox.showinfo('队列为空','请先加入任务，或直接点击“生成预览”。');return
        self.run_jobs(todo)
    def analyze(self):
        if self.busy:return
        j=self.add()
        if j:self.run_jobs([dict(j)],export=False)
    def request_stop(self):
        if self.busy:self.stop.set();self.status.set('正在停止，请等待当前步骤退出…')
    def progress(self,s):self.events.put(('log',s))
    def log_line(self,s):
        text=datetime.now().strftime('%H:%M:%S')+'  '+s
        self.log.insert('end',text+'\n');self.log.see('end')
        with (DATA/'processing.log').open('a',encoding='utf8') as f:f.write(text+'\n')
    def heartbeat(self):
        if self.busy:self.root.title('杨宁视频工作室 · 处理中 '+str(int(time.monotonic()-self.started))+'秒 · '+VERSION)
        else:self.root.title('杨宁视频工作室 · 成片制作 · '+VERSION)
        self.root.after(1000,self.heartbeat)
    def listen(self,optimized):
        try:j=self.current(True);folder=Path(j['analysis'])
        except Exception:messagebox.showinfo('先分析','请选中已完成分析的任务。');return
        if j.get('sequence'):
            try:folder=Path(json.loads((folder/'report.json').read_text(encoding='utf8'))['body_analysis'])
            except Exception:messagebox.showinfo('先处理正文','请先完成新版项目预览，再试听正文配音。');return
        if (folder/'clean_project.json').is_file():self.clean_review();return
        def go():
            if optimized:preview_audio(folder,self.stop)
            names=json.loads((folder/'audio_versions.json').read_text(encoding='utf8'));open_path(folder/names['B' if optimized else 'A'])
        self.worker(go)
    def edit_plan(self):
        if self.busy:return
        try:
            j=self.current(True);base=Path(j['analysis'])
            if j.get('sequence'):base=Path(json.loads((base/'report.json').read_text(encoding='utf8'))['body_analysis'])
            path=base/'pause_plan.csv';rows=import_plan(path)
        except Exception:messagebox.showinfo('先分析','请先分析选中的任务。');return
        win=tk.Toplevel(self.root);win.title('停顿表 · 双击修改，取消行即可保留原停顿');win.geometry('900x420')
        table=ttk.Treeview(win,columns=('enabled','time','kind','seconds','why'),show='headings');table.pack(fill='both',expand=True)
        for k,label,width in [('enabled','应用',50),('time','原配音位置',150),('kind','类型',70),('seconds','变化秒数',80),('why','原因',490)]:table.heading(k,text=label);table.column(k,width=width)
        def refresh():
            table.delete(*table.get_children())
            for i,r in enumerate(rows):table.insert('','end',iid=str(i),values=('是' if r['enabled'] else '否',f"{r['start']:.2f}–{r['end']:.2f}",'缩短' if r['kind']=='cut' else '增加',f"{r['seconds']:.2f}",r['reason']))
        def edit(event=None):
            if not table.selection():return
            r=rows[int(table.selection()[0])]
            if not messagebox.askyesno('应用此调整','应用该行调整？\n选择“否”保留原配音停顿。',parent=win):r['enabled']=False;refresh();return
            if r['kind']=='cut':
                gap=r['safe_end']-r['safe_start'];val=simpledialog.askfloat('保留停顿','原空白 %.2f 秒；希望保留几秒？'%gap,initialvalue=max(.3,gap-r['seconds']),minvalue=.3,maxvalue=gap,parent=win)
                if val is None:return
                r['start']=r['safe_start']+val/2;r['end']=r['safe_end']-val/2;r['seconds']=r['end']-r['start'];r['enabled']=r['seconds']>.001
            else:
                val=simpledialog.askfloat('增加留白','增加几秒？',initialvalue=r['seconds'],minvalue=0,maxvalue=1.2,parent=win)
                if val is None:return
                r['seconds']=val;r['enabled']=val>0
            refresh()
        table.bind('<Double-1>',edit);refresh()
        def save():
            export_plan(rows,path)
            if j.get('sequence'):
                self.sequence_panel.pause_override=rows;j['_pause_override']=rows
                self.sequence_panel.approved_preview='';self.sequence_panel.changed();self.save()
            win.destroy();self.progress('停顿计划已保存，B试听和导出会使用新计划。')
        ttk.Button(win,text='修改所选',command=edit).pack(side='left',padx=6,pady=8);ttk.Button(win,text='保存',command=save).pack(side='right',padx=8)
    def advanced(self):
        if self.busy:return
        self.set_activity(True)
        win=tk.Toplevel(self.root);win.title('更多设置 · 默认无需修改');win.geometry('760x760');box=ttk.Frame(win,padding=15);box.pack(fill='both',expand=True)
        ttk.Radiobutton(box,text='按所选语言参考稿自动定位（默认）',variable=self.v['alignment'],value='auto').pack(anchor='w')
        ttk.Radiobutton(box,text='使用已校对配音SRT时间轴（可选）',variable=self.v['alignment'],value='timed').pack(anchor='w')
        line=ttk.Frame(box);line.pack(fill='x',pady=8);ttk.Label(line,text='独立配音SRT（可留空）').pack(side='left');ttk.Entry(line,textvariable=self.v['target_srt']).pack(side='left',fill='x',expand=True);ttk.Button(line,text='选择',command=lambda:self.pick('target_srt')).pack(side='left')
        ttk.Checkbutton(box,text='自动剪短长空白（保留自然停顿）',variable=self.auto_cut).pack(anchor='w')
        ttk.Label(box,text='日语字词间多余空白压缩已启用；保留短停顿、换气和句末停顿。日志显示前后时长与删除秒数。',wraplength=660).pack(anchor='w',pady=10)
        for controls in [[('加入批量队列',self.add),('批量分析 / 试听',self.start),('重试所选',self.retry),('删除所选',self.remove)],[('仅分析/试听',self.analyze),('A 原配音',lambda:self.listen(False)),('B 优化配音',lambda:self.listen(True)),('停顿表',self.edit_plan)]]:
            line=ttk.Frame(box);line.pack(fill='x',pady=5)
            for label,fn in controls:ttk.Button(line,text=label,command=fn).pack(side='left',padx=(0,6))
        ttk.Button(box,text='重新导出所选任务',command=lambda:(win.destroy(),self.final_export())).pack(anchor='w',pady=8)
        ttk.Button(box,text='完成设置',command=win.destroy).pack(anchor='e',pady=12)
    def retry(self):
        if self.busy:return
        try:j=dict(self.current(True))
        except Exception as e:messagebox.showinfo('选择任务',str(e));return
        if j.get('clean_project'):
            messagebox.showinfo('重新生成预览','请回主界面选择同一视频，再点生成预览。旧工程保留。');return
        j.pop('analysis',None);j.pop('result',None);self.run_jobs([j],export=False)
    def remove(self):
        if self.busy:return
        self.jobs=[j for j in self.jobs if j['id'] not in self.table.selection()];self.refresh()
    def show_detail(self,event=None):
        j=self.current()
        if j:messagebox.showinfo('任务详情',j.get('error') or j.get('step') or j.get('status',''))
    def open_result(self):
        try:j=self.current(True);open_path(j.get('result') or j.get('analysis') or j['output'])
        except Exception as e:messagebox.showerror('打开结果',str(e))
    def poll(self):
        try:
            while True:
                e=self.events.get_nowait()
                if e[0]=='idle':
                    self.busy=False;self.bar.stop();self.main_button.state(['!disabled'])
                    if not self.jobs or self.status.get().startswith('已启动'):self.status.set('操作完成。')
                elif e[0]=='desktop_update':self.desktop_updates.handle(e[1:])
                elif e[0]=='repair_preview_ready':
                    self.sequence_panel.repair_previews[e[1]]=e[2];open_path(e[3])
                elif e[0]=='sequence_preview_ready':
                    self.sequence_panel.last_preview=e[1];self.sequence_panel.update();open_path(e[2])
                elif e[0]=='separation_preview_ready':
                    self.sequence_panel.separation_preview_token=e[1];open_path(e[2])
                elif e[0]=='style_saved':
                    self.pending_style=e[1]
                    (DATA/'style_no_denoise.json').write_text(json.dumps(e[1],ensure_ascii=False,indent=2),encoding='utf8')
                    self.log_line('排版已保存，下次一键导出会应用。')
                elif e[0]=='review_refresh':
                    try:e[1]();e[2].set('修改已保存，试听已更新。')
                    except tk.TclError:pass
                elif e[0]=='publish_done':
                    self.status.set('发布成片 / 预览已完成：'+e[1]);self.log_line(self.status.get());open_path(e[1])
                elif e[0]=='error':self.set_activity(True);self.log_line('失败：'+e[1]);self.status.set('失败：'+e[1])
                elif e[0]=='log':self.log_line(e[1])
                elif e[0]=='progress':
                    self.status.set(e[2]);self.log_line(e[2])
                    for j in self.jobs:
                        if j['id']==e[1]:j['step']=e[2]
                    self.refresh()
                elif e[0]=='sound_ready':
                    self.root.after(200,self.clean_review if e[1] else self.full_sound_review)
                elif e[0]=='state':
                    if e[2]=='失败':self.set_activity(True)
                    for j in self.jobs:
                        if j['id']==e[1]:
                            j['status']=e[2];j.update(e[3]);self.status.set(e[2]+('：'+j['error'] if j.get('error') else ''))
                    self.refresh()
        except queue.Empty:pass
        self.root.after(100,self.poll)
    def close(self):
        if self.busy:messagebox.showinfo('正在处理','请先点击停止，等待任务结束后关闭。');return
        self.save();self.root.destroy()
if __name__=='__main__':App(tk.Tk()).root.mainloop()
