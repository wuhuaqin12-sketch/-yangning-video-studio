"""Cloud music-only tool; all Tk accesses stay on the GUI thread."""
import json,queue,threading,webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from mvsep_music import process,check_account,fingerprint

def open_music(app,source=None,use_intro=False):
    win=tk.Toplevel(app.root);win.title('仅保留背景音乐 · MVSep 云端 · 测试版');win.geometry(f'840x{min(740,win.winfo_screenheight()-100)}')
    canvas=tk.Canvas(win,highlightthickness=0);scroll=ttk.Scrollbar(win,orient='vertical',command=canvas.yview)
    scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True);canvas.configure(yscrollcommand=scroll.set)
    box=ttk.Frame(canvas,padding=14);item=canvas.create_window((0,0),window=box,anchor='nw')
    box.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
    win.bind('<MouseWheel>',lambda e:canvas.yview_scroll(-int(e.delta/120),'units'))
    ttk.Label(box,text='MVSep DnR v3 · Mel＋SCNet · 直接从原始混合音轨提取',font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w')
    ttk.Label(box,text='只保留 Music；舍弃 Speech / Sfx。不会自动改用 Demucs 或 MDX HQ3。\n需要联网：仅上传所选原视频的音轨，画面不上传。Token 仅保留在本窗口内。',wraplength=740).pack(anchor='w',pady=8)
    video=tk.StringVar(value=source or app.v['video'].get());output=tk.StringVar(value=app.v['output'].get());token=tk.StringVar();start=tk.StringVar(value='0');consent=tk.BooleanVar();charges=tk.BooleanVar();approved=tk.BooleanVar()
    def row(label,var,picker=None,secret=False):
        f=ttk.Frame(box);f.pack(fill='x',pady=4);ttk.Label(f,text=label,width=17).pack(side='left');ttk.Entry(f,textvariable=var,show='*' if secret else '').pack(side='left',fill='x',expand=True)
        if picker:ttk.Button(f,text='选择',command=lambda:var.set(picker() or var.get())).pack(side='left',padx=4)
    row('原始视频',video,lambda:filedialog.askopenfilename(parent=win,filetypes=[('视频','*.mp4 *.mov *.mkv *.avi'),('全部','*.*')]))
    row('输出文件夹',output,lambda:filedialog.askdirectory(parent=win));row('MVSep API Token',token,secret=True);row('试听开始秒数',start)
    ttk.Label(box,text='注册账户：普通 API 有限制；通常每次≤10分钟、≤100MB、同时1任务。\nPremium 上限100分钟/1000MB；实际权限以官网及账户为准。Credits 预付费，\n官方示例 US$3/60、US$5/200；此模型基础倍率1，最低1 credit/任务（启用付费时）。\n20秒试听和整段是两次独立云端任务，可能分别扣费；不自动开启账户付费。',wraplength=740).pack(anchor='w',pady=6)
    links=ttk.Frame(box);links.pack(anchor='w')
    for text,url in [('注册 / 获取 Token','https://mvsep.com/en/full_api'),('官方费用与额度','https://mvsep.com/en/plans')]:ttk.Button(links,text=text,command=lambda u=url:webbrowser.open(u)).pack(side='left',padx=3)
    ttk.Checkbutton(box,text='同意将原始音轨上传 MVSep 云端进行此项处理',variable=consent).pack(anchor='w',pady=4)
    ttk.Checkbutton(box,text='已了解账户可能扣除 credits（按官网实际收费）',variable=charges).pack(anchor='w')
    ttk.Checkbutton(box,text='已试听本次20秒结果，确认效果可用于处理完整视频',variable=approved).pack(anchor='w',pady=4)
    status=tk.StringVar(value='尚未上传。先检查账户，再生成20秒试听。');ttk.Label(box,textvariable=status,wraplength=740).pack(anchor='w',pady=6)
    bar=ttk.Progressbar(box,mode='indeterminate');bar.pack(fill='x')
    buttons=ttk.Frame(box);buttons.pack(fill='x',pady=8)
    events=queue.Queue();stop=threading.Event();state={'busy':False,'last':None,'preview':None,'result':None};workers=[]
    def launch(kind):
        if state['busy']:return
        if app.busy:messagebox.showinfo('请稍候','请等待工作室当前任务结束。',parent=win);return
        values=(video.get(),output.get(),token.get().strip(),start.get(),consent.get(),charges.get(),approved.get())
        src,dest,key,begin,ok,cost,accept=values
        if kind!='account' and not ok:messagebox.showinfo('需要上传授权','请先勾选同意上传音轨。',parent=win);return
        if kind=='full' and (not accept or not state['preview']):messagebox.showinfo('先试听','请先生成并试听20秒结果，再勾选确认。',parent=win);return
        state['busy']=True;state['last']=kind;stop.clear();bar.start(15)
        def work():
            try:
                if kind=='account':check_account(key,lambda s:events.put(('status',s)))
                else:
                    if kind=='full' and fingerprint(src,stop)!=state['preview']['original_sha256']:raise ValueError('原始视频已改变，请重新进行20秒试听。')
                    result=process(src,dest,key,stop,lambda s:events.put(('status',s)),seconds=20 if kind=='preview' else None,start=float(begin) if kind=='preview' else 0,allow_charges=cost)
                    events.put((kind,str(result)))
            except Exception as e:events.put(('error',str(e).replace(key,'[Token]') if key else str(e)))
            finally:events.put(('idle',None))
        t=threading.Thread(target=work,daemon=True);workers.append(t);t.start()
    def listen():
        if state['result']:
            from app import open_path
            open_path(state['result'])
    def assign():
        if not state['result'] or '_20秒试听' in Path(state['result']).stem:messagebox.showinfo('先处理完整片头','需要完整结果，不能用20秒试听替代完整片头。',parent=win);return
        p=app.sequence_panel;p.v['intro_video'].set(state['result']);p.v['intro_enabled'].set(True);p.v['intro_mode'].set('original');p.update();status.set('已填入片头，选择“保留全部原声”播放此纯音乐成品；原素材未修改。')
    for text,fn in [('检查账户',lambda:launch('account')),('20秒试听测试',lambda:launch('preview')),('处理完整视频',lambda:launch('full')),('重试原任务',lambda:launch(state['last']) if state['last'] else None),('停止等待',stop.set),('播放结果',listen)]:ttk.Button(buttons,text=text,command=fn).pack(side='left',padx=2)
    if use_intro:ttk.Button(box,text='将完整音乐结果用于片头',command=assign).pack(anchor='w')
    ttk.Label(box,text='完整输出直接复制视频流并验证画面一致性；试听片段为精确定位重新编码。\n网络中断后重试恢复已知云端任务，不自动重复上传。停止等待不保证取消云端计费。\n若提交结果不明确，会阻止自动重发；请先在官网核对任务。',wraplength=740).pack(anchor='w',pady=6)
    def poll():
        if not win.winfo_exists():return
        while not events.empty():
            kind,value=events.get()
            if kind=='idle':state['busy']=False;bar.stop()
            elif kind in ('preview','full'):
                state['result']=value
                if kind=='preview':state['preview']=json.loads(Path(value).with_suffix('.mvsep.json').read_text(encoding='utf8'));approved.set(False)
                status.set('已生成：'+value+'。请点击“播放结果”检查中文残留、音乐失真和音量。')
            elif kind=='error':status.set('失败：'+value)
            else:status.set(value)
        win.after(150,poll)
    def close():
        if state['busy']:stop.set();status.set('正在停止本地操作，退出后云端任务可能继续；请稍候再关闭。');return
        token.set('');win.destroy()
    win.protocol('WM_DELETE_WINDOW',close);win.after(150,poll);return win
