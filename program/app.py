import os,json,threading,queue,uuid,subprocess,time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog
from engine import preview_audio,Cancelled,VERSION
from workflow import normalize,execute
from audio_edit import import_plan,export_plan
DATA=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'YangNingStudio'
DATA.mkdir(parents=True,exist_ok=True)
# Keep old queues intact; stale settings and analysis from old versions are not run.
STATE=DATA/'queue_noerase_v055.json'
def open_path(p):
    if os.name=='nt':os.startfile(str(p))
    else:subprocess.Popen(['xdg-open',str(p)])
class App:
    def __init__(self,root):
        self.root=root;root.title('杨宁视频工作室 · 生成预览 · '+VERSION)
        root.geometry('1000x740');root.minsize(840,660)
        self.jobs=[];self.busy=False;self.stop=threading.Event();self.events=queue.Queue();self.started=0
        defaults=dict(video='',audio='',source_srt='',target_srt='',output=str(Path.home()/'Videos'/'YangNingOutputs'),name='',language='ja',alignment='auto',audio_profile='off',font='',font_percent='5.6')
        self.v={k:tk.StringVar(value=v) for k,v in defaults.items()}
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
        pane=ttk.Frame(root,padding=16);pane.pack(fill='both',expand=True)
        ttk.Label(pane,text='杨宁视频工作室',font=('Microsoft YaHei UI',22,'bold')).pack(anchor='w')
        ttk.Label(pane,text='配音与字幕同步 · 自然停顿调整 · 选好素材，一键导出').pack(anchor='w',pady=(3,12))
        form=ttk.LabelFrame(pane,text='选择素材',padding=12);form.pack(fill='x')
        for i,(k,label) in enumerate([('video','1  原视频'),('audio','配音（可留空）'),('source_srt','原视频时间轴语言'),('output','保存到')]):
            ttk.Label(form,text=label).grid(row=(i if i<3 else 4),column=0,sticky='w',padx=(0,10),pady=5)
            ttk.Entry(form,textvariable=self.v[k]).grid(row=(i if i<3 else 4),column=1,sticky='ew')
            ttk.Button(form,text='选择',command=lambda key=k:self.pick(key)).grid(row=(i if i<3 else 4),column=2,padx=(6,0))
        form.columnconfigure(1,weight=1)
        ttk.Label(form,text='SRT / 带时间轴TXT：时间对应原视频，文字可用对应译文；自动匹配配音时，参考文字须与配音语言一致。',wraplength=650).grid(row=5,column=0,columnspan=3,sticky='w',pady=(5,0))
        self.target_label=ttk.Label(form,text='独立配音SRT（可选）')
        self.target_entry=ttk.Entry(form,textvariable=self.v['target_srt'])
        self.target_button=ttk.Button(form,text='选择',command=lambda:self.pick('target_srt'))
        self.target_label.grid(row=3,column=0,sticky='w',padx=(0,10),pady=5);self.target_entry.grid(row=3,column=1,sticky='ew');self.target_button.grid(row=3,column=2,padx=(6,0))
        self.language_name=tk.StringVar(value='日语')
        for widget in (self.target_label,self.target_entry,self.target_button):widget.grid_remove()

        ttk.Label(pane,text='不额外调速。剪掉的空白会同步调整画面和字幕；多余词先试听再决定。').pack(anchor='w',pady=(8,4))
        line=ttk.Frame(pane);line.pack(fill='x',pady=4)
        ttk.Button(line,text='声音处理 / 降噪试听',command=self.sound_settings).pack(side='left')
        ttk.Button(line,text='更多设置 / 批量',command=self.advanced).pack(side='right')
        ttk.Label(pane,text='不会自动删词或擦画面字幕。可先选一小段试听，再决定修改。').pack(anchor='w',pady=(0,8))
        line=ttk.Frame(pane);line.pack(fill='x',pady=6)
        self.main_button=ttk.Button(line,text='一键制作并导出',command=self.clean_start);self.main_button.pack(side='left',ipadx=18,ipady=6)
        ttk.Button(line,text='停止',command=self.request_stop).pack(side='left',padx=8)
        ttk.Button(line,text='预览（可选）',command=self.clean_review).pack(side='left')
        self.status=tk.StringVar(value='选择素材与排版后，点击“一键制作并导出”。不用先试听。')
        ttk.Label(pane,textvariable=self.status,wraplength=900).pack(anchor='w',pady=(8,3))
        self.bar=ttk.Progressbar(pane,mode='indeterminate');self.bar.pack(fill='x',pady=(0,8))
        self.table=ttk.Treeview(pane,columns=('name','status','detail'),show='headings',height=5)
        self.table.pack(fill='both',expand=True,pady=7)
        for key,label,width in [('name','任务',210),('status','状态',135),('detail','当前步骤 / 失败原因',550)]:self.table.heading(key,text=label);self.table.column(key,width=width,minwidth=70)
        self.table.bind('<Double-1>',self.show_detail)
        self.log=tk.Text(pane,height=5,wrap='word');self.log.pack(fill='x',pady=(7,0))
        from desktop_ui import DesktopUpdates
        self.desktop_updates=DesktopUpdates(self,pane)
        self.refresh();root.after(100,self.poll);root.after(1000,self.heartbeat);root.protocol('WM_DELETE_WINDOW',self.close)
    def clean_start(self):
        if self.busy:return
        from clean_project import prepare,load,save,export
        style=dict(self.pending_style)
        job={k:v.get() for k,v in self.v.items()}
        job.update(id=uuid.uuid4().hex,name=Path(job['video']).stem or '原声预览',status='待处理',clean_project=True,auto_cut=self.auto_cut.get())
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
        win=tk.Toplevel(self.root);win.title('声音处理');win.geometry('680x560')
        box=ttk.Frame(win,padding=18);box.pack(fill='both',expand=True)
        ttk.Radiobutton(box,text='关闭降噪',variable=self.v['audio_profile'],value='off').pack(anchor='w',pady=4)
        ttk.Radiobutton(box,text='启用温和降噪（底噪、沙沙声、短促点击声）',variable=self.v['audio_profile'],value='v11').pack(anchor='w',pady=4)
        ttk.Radiobutton(box,text='V11 加强降噪（本次：RNNoise + 低频与点击声清理）',variable=self.v['audio_profile'],value='v11_deep').pack(anchor='w',pady=4)
        def v11_preset():
            self.v['audio_profile'].set('v11_deep');self.v['audio_separate'].set(True)
        ttk.Button(box,text='按本次标准设置：人声分离 + 加强降噪',command=v11_preset).pack(anchor='w',pady=6)
        ttk.Button(box,text='查看 / 复制本次去噪指令',command=self.sound_rules).pack(anchor='w',pady=4)
        ttk.Checkbutton(box,text='分离人声与背景音乐（独立可选）',variable=self.v['audio_separate']).pack(anchor='w',pady=8)
        ttk.Label(box,text='人声分离首次需要联网下载较大运行环境和模型，仅支持 Python 3.10–3.12；以后在本机处理。',wraplength=570).pack(anchor='w',pady=4)
        ttk.Label(box,text='设置用于新任务。保留原文件和原声；不自动删词、不主动改变音调。杂声与人声重叠时可能残留或影响音质，请对比试听。',wraplength=570).pack(anchor='w',pady=4)
        def listen():
            if self.busy:return
            job={k:v.get() for k,v in self.v.items()}
            if not Path(job.get('video','')).is_file():messagebox.showinfo('选择视频','请先选择视频。',parent=win);return
            job.update(id=uuid.uuid4().hex,name=Path(job['video']).stem,clean_project=True,auto_cut=self.auto_cut.get(),status='待处理')
            self.jobs.append(job);self.refresh();self.table.selection_set(job['id']);win.destroy()
            def work():
                try:
                    if job.get('audio'):
                        folder=execute(job,self.stop,self.events.put,export=False)
                        if folder:self.events.put(('sound_ready',False))
                    else:
                        from clean_project import prepare
                        folder=prepare(job,self.stop,self.progress,make_previews=False)
                        if self.pending_style:
                            from clean_project import load,save
                            m=load(folder);m['style']=dict(self.pending_style);save(Path(folder)/'clean_project.json',m)
                        self.events.put(('state',job['id'],'待试听',dict(analysis=folder)))
                        self.events.put(('sound_ready',True))
                except Cancelled:self.events.put(('state',job['id'],'已停止',dict(error='用户停止了任务')))
                except Exception as e:self.events.put(('state',job['id'],'失败',dict(error=str(e))))
            self.worker(work)
        ttk.Button(box,text='生成原声 / 处理后试听',command=listen).pack(anchor='w',pady=10)
        def save_sound():
            (DATA/'sound_preferences.json').write_text(json.dumps({k:self.v[k].get() for k in ('audio_profile','audio_separate')}),encoding='utf8');win.destroy()
        ttk.Button(box,text='保存设置，返回制作',command=save_sound).pack(anchor='e')
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
        win=tk.Toplevel(self.root);win.title('试听与修改片段');win.geometry('710x440')
        box=ttk.Frame(win,padding=18);box.pack(fill='both',expand=True)
        ttk.Label(box,text='先试听，再决定；范围使用原视频秒数。',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w')
        start=tk.StringVar(value=str(m.get('preview_start',0)));end=tk.StringVar(value=str(m.get('preview_end',15)))
        line=ttk.Frame(box);line.pack(fill='x',pady=12)
        for label,var in [('开始（秒）',start),('结束（秒）',end)]:
            ttk.Label(line,text=label).pack(side='left');ttk.Entry(line,textvariable=var,width=10).pack(side='left',padx=8)
        note=tk.StringVar(value='试听最多60秒；修改范围可精确输入到0.01秒。')
        ttk.Label(box,textvariable=note,wraplength=650).pack(anchor='w')
        history=tk.Text(box,height=7,wrap='word');history.pack(fill='both',expand=True,pady=10)
        def refresh():
            data=load(folder);history.delete('1.0','end')
            for e in data['edits']:history.insert('end',('静音' if e['kind']=='mute' else '剪掉')+f" {e['start']:.2f}—{e['end']:.2f} 秒\n")
            history.insert('1.0',f"已自动剪短{len(data.get('auto_edits',[]))}处长空白。\n")
            if not data['edits']:history.insert('end','还没有手动修改。原声始终保留。')
        refresh()
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
        ttk.Label(box,text='“静音”保留时长；“剪掉”同步缩短音画与字幕。多余词需人工试听确认。',wraplength=650).pack(anchor='w',pady=8)
    def final_export(self):
        if self.busy:return
        try:j=dict(self.current(True));folder=Path(j['analysis'])
        except Exception:messagebox.showinfo('选择任务','请选中已制作或已分析的任务，再重新导出。');return
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
        lang={'英语':'en','日语':'ja','法语':'fr','德语':'de','西班牙语':'es','意大利语':'it','韩语':'ko','葡萄牙语':'pt','中文':'zh','印尼语':'id','其他语言':'other'}[self.language_name.get()]
        self.v['language'].set(lang);self.v['alignment'].set('timed' if lang=='other' else 'auto');self.v['target_srt'].set('')
        for widget in (self.target_label,self.target_entry,self.target_button):
            if lang!='other':widget.grid_remove()
            else:widget.grid()
    def pick(self,k):
        selected=filedialog.askdirectory() if k=='output' else filedialog.askopenfilename()
        if selected:self.v[k].set(selected)
    def settings(self):
        j={k:v.get() for k,v in self.v.items()};j['publish_settings']=dict(self.pending_style);j.pop('preview_time',None)
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
        else:self.root.title('杨宁视频工作室 · 生成预览 · '+VERSION)
        self.root.after(1000,self.heartbeat)
    def listen(self,optimized):
        try:j=self.current(True);folder=Path(j['analysis'])
        except Exception:messagebox.showinfo('先分析','请选中已完成分析的任务。');return
        if (folder/'clean_project.json').is_file():self.clean_review();return
        def go():
            if optimized:preview_audio(folder,self.stop)
            names=json.loads((folder/'audio_versions.json').read_text(encoding='utf8'));open_path(folder/names['B' if optimized else 'A'])
        self.worker(go)
    def edit_plan(self):
        if self.busy:return
        try:j=self.current(True);path=Path(j['analysis'])/'pause_plan.csv';rows=import_plan(path)
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
        def save():export_plan(rows,path);win.destroy();self.progress('停顿计划已保存，B试听和导出会使用新计划。')
        ttk.Button(win,text='修改所选',command=edit).pack(side='left',padx=6,pady=8);ttk.Button(win,text='保存',command=save).pack(side='right',padx=8)
    def advanced(self):
        if self.busy:return
        win=tk.Toplevel(self.root);win.title('高级设置 · 默认无需修改');win.geometry('760x760');box=ttk.Frame(win,padding=15);box.pack(fill='both',expand=True)
        line=ttk.Frame(box);line.pack(fill='x',pady=6);ttk.Label(line,text='配音语言').pack(side='left')
        language_box=ttk.Combobox(line,textvariable=self.language_name,values=('英语','日语','法语','德语','西班牙语','意大利语','韩语','葡萄牙语','中文','印尼语','其他语言'),state='readonly',width=10);language_box.pack(side='left',padx=8);language_box.bind('<<ComboboxSelected>>',self.language_changed)
        ttk.Label(box,text='已接入语言可复用主界面SRT：文字须匹配所选语言配音，原时间对应画面；配音时间自动定位。',wraplength=660).pack(anchor='w',pady=5)
        ttk.Radiobutton(box,text='按所选语言参考稿自动定位（默认）',variable=self.v['alignment'],value='auto').pack(anchor='w')
        ttk.Radiobutton(box,text='使用已校对配音SRT时间轴（可选）',variable=self.v['alignment'],value='timed').pack(anchor='w')
        line=ttk.Frame(box);line.pack(fill='x',pady=8);ttk.Label(line,text='独立配音SRT（可留空）').pack(side='left');ttk.Entry(line,textvariable=self.v['target_srt']).pack(side='left',fill='x',expand=True);ttk.Button(line,text='选择',command=lambda:self.pick('target_srt')).pack(side='left')
        ttk.Button(box,text='配音匹配并导出',command=lambda:(win.destroy(),self.one_click())).pack(anchor='w',pady=5)
        ttk.Button(box,text='标题 / 字幕 / 封面',command=lambda:(win.destroy(),self.publish())).pack(anchor='w',pady=5)
        ttk.Checkbutton(box,text='自动剪短长空白（保留自然停顿）',variable=self.auto_cut).pack(anchor='w')
        ttk.Checkbutton(box,text='把新字幕写入画面（默认不写入，仍导出SRT）',variable=self.v['burn']).pack(anchor='w',pady=5)
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
                elif e[0]=='style_saved':
                    self.pending_style=e[1]
                    (DATA/'style_no_denoise.json').write_text(json.dumps(e[1],ensure_ascii=False,indent=2),encoding='utf8')
                    self.log_line('排版已保存，下次一键导出会应用。')
                elif e[0]=='review_refresh':
                    try:e[1]();e[2].set('修改已保存，试听已更新。')
                    except tk.TclError:pass
                elif e[0]=='publish_done':
                    self.status.set('发布成片 / 预览已完成：'+e[1]);self.log_line(self.status.get());open_path(e[1])
                elif e[0]=='error':self.log_line('失败：'+e[1]);self.status.set('失败：'+e[1])
                elif e[0]=='log':self.log_line(e[1])
                elif e[0]=='progress':
                    self.status.set(e[2]);self.log_line(e[2])
                    for j in self.jobs:
                        if j['id']==e[1]:j['step']=e[2]
                    self.refresh()
                elif e[0]=='sound_ready':
                    self.root.after(200,self.clean_review if e[1] else lambda:self.listen(True))
                elif e[0]=='state':
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
