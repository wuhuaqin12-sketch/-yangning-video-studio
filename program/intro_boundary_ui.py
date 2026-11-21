"""Preview and confirm automatically proposed intro/video and narration splits."""
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from intro_boundary import detect,verify,preview,video_only_boundary

class IntroDialog:
    def __init__(self,panel):
        self.panel=panel;self.app=panel.app;self.result=None;self.seen=set()
        self.win=tk.Toplevel(self.app.root);self.win.title('片头视频 / 合并配音自动分界');self.win.geometry('800x460')
        page=ttk.Frame(self.win,padding=16);page.pack(fill='both',expand=True)
        ttk.Label(page,text='不用在 SRT 里加“正文开始/结束”标记，也不用手动填写秒数。按片头最后字幕编号定位；软件读取下一条字幕作为正文开始，最后一条字幕作为正文结束。候选需先看画面、试听配音。',wraplength=750).pack(anchor='w')
        row=ttk.Frame(page);row.pack(fill='x',pady=3)
        ttk.Label(row,textvariable=panel.intro_cue_status,wraplength=520).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='从 SRT 选择片头最后一句',command=panel.pick_intro_last_cue).pack(side='left',padx=5)
        ttk.Label(page,text='主页面 SRT 时间对应原视频画面。下一条字幕自动作为正文开始，最后一条字幕自动作为正文结束；其他视频只需在列表里选片头最后一句，不用手写编号或秒数。字幕文字须与配音一致，或另提供已对齐配音 SRT。',wraplength=750).pack(anchor='w',pady=6)
        ttk.Label(page,text='已对齐合并配音的SRT（可选，不是原视频时间轴）').pack(anchor='w')
        row=ttk.Frame(page);row.pack(fill='x',pady=5);self.aligned=tk.StringVar(value='')
        ttk.Entry(row,textvariable=self.aligned).pack(side='left',fill='x',expand=True);ttk.Button(row,text='选择',command=self.pick).pack(side='left',padx=6)
        ttk.Label(page,text='未提供已对齐SRT时，调用现有本地语音定位。首次可能配置组件/下载约460MB模型，可停止；配音不上传。粤语等未支持语言须提供已对齐SRT。',wraplength=750).pack(anchor='w',pady=6)
        ttk.Button(page,text='自动定位片头与配音分界',command=self.find).pack(anchor='w',pady=6)
        ttk.Button(page,text='仅定位视频片头分界（配音定位失败时使用）',command=self.find_video_only).pack(anchor='w',pady=3)
        self.status=tk.StringVar(value='自动结果不直接填写主页面。原视频、SRT或配音变更后需重新定位。')
        ttk.Label(page,textvariable=self.status,wraplength=750).pack(anchor='w',pady=8)
        row=ttk.Frame(page);row.pack(fill='x')
        self.vbutton=ttk.Button(row,text='预览视频分界',command=lambda:self.listen('video'),state='disabled');self.vbutton.pack(side='left')
        self.abutton=ttk.Button(row,text='试听配音分界',command=lambda:self.listen('audio'),state='disabled');self.abutton.pack(side='left',padx=8)
        self.ok=ttk.Button(row,text='确认填写两个分界',command=self.accept,state='disabled');self.ok.pack(side='left')
        ttk.Button(page,text='关闭',command=self.win.destroy).pack(anchor='e',pady=16)
    def pick(self):
        value=filedialog.askopenfilename(parent=self.win,filetypes=[('已对齐配音SRT','*.srt')])
        if value:self.aligned.set(value);self.result=None;self.seen.clear();self.ok.state(['disabled'])
    def inputs(self):return self.app.v['video'].get(),self.app.v['audio'].get(),self.app.v['source_srt'].get()
    def launch(self,kind,fn):
        if self.app.busy:messagebox.showinfo('正在处理','请等待当前任务完成或先停止。',parent=self.win);return
        def work():
            try:value=fn()
            except Exception as e:self.app.events.put(('utility_dialog_event',self,'failed',str(e)));return
            self.app.events.put(('utility_dialog_event',self,kind,value))
        self.app.worker(work)
    def find(self):
        if self.app.busy:return
        try:
            video,audio,srt=self.inputs();last=int(float(self.panel.v['combined_intro_last_cue'].get()));language=self.app.v['language'].get();aligned=self.aligned.get();cached=self.panel.v['combined_aligned_srt'].get();token=self.panel.v['combined_alignment_token'].get()
            if not audio:raise ValueError('请先选择整段配音文件；视频时间轴 SRT 和配音 SRT 使用各自独立时间。')
            self.folder=self.panel.autosave.parent/('IntroBoundary_'+uuid.uuid4().hex);self.result=None;self.seen.clear();self.ok.state(['disabled'])
            self.status.set('正在定位；如需本地语音定位，进度显示在主页面运行记录。');self.app.set_activity(True)
            def locate():
                chosen=aligned
                if not chosen and cached and token:
                    try:
                        from intro_boundary import alignment_token
                        if alignment_token(video,audio,srt,cached)==token:chosen=cached;self.app.progress('复用已完成的完整配音定位，不重新运行模型')
                    except (OSError,ValueError):pass
                return detect(video,audio,srt,language,last,chosen,self.folder,self.app.stop,self.app.progress)
            self.launch('found',locate)
        except Exception as e:messagebox.showerror('片头自动定位',str(e),parent=self.win)
    def find_video_only(self):
        if self.app.busy:return
        try:
            video,_,srt=self.inputs()
            last=int(float(self.panel.v['combined_intro_last_cue'].get()))
            candidate=video_only_boundary(video,srt,last,self.app.stop)
            if not messagebox.askyesno('仅定位视频分界',f'正文画面开始：{candidate["video"]:.3f} 秒（第{candidate["body_id"]}条）。\n只填写视频分界；配音分界仍须单独定位或人工确认。是否应用？',parent=self.win):return
            self.panel.v['combined_intro_end'].set(f'{candidate["video"]:.3f}')
            self.panel.approved_preview='';self.panel.update()
            self.status.set('已填写视频分界；配音分界尚未确认，不能据此认定音画同步完成。')
        except Exception as e:
            self.status.set(f'视频分界定位失败：{e}')
            messagebox.showwarning('视频分界定位失败',str(e),parent=self.win)
    def listen(self,kind):
        if not self.result:return
        video,audio,srt=self.inputs();candidate=self.result
        self.launch('preview',lambda:preview(candidate,video,audio,srt,kind,self.folder,self.app.stop))
    def receive(self,kind,value):
        if not self.win.winfo_exists():return
        if kind=='failed':self.status.set(str(value));messagebox.showwarning('未应用自动分界',str(value),parent=self.win);return
        if kind=='found':
            try:verify(value,*self.inputs())
            except Exception as e:self.status.set(str(e));return
            self.result=value;self.seen.clear();self.vbutton.state(['!disabled']);self.abutton.state(['!disabled']);self.ok.state(['disabled'])
            self.status.set(f'视频片头结束候选 {value["video"]:.3f}秒；合并配音分界候选 {value["audio"]:.3f}秒。{value["warning"]}')
        if kind=='preview':
            if not self.result or value['token']!=self.result['token']:return
            self.seen.add(value['kind'])
            if self.seen=={'video','audio'}:self.ok.state(['!disabled'])
            return value['path']
    def accept(self):
        if self.app.busy:return
        try:
            if not self.result or self.seen!={'video','audio'}:raise ValueError('请先看视频分界预览，并试听配音分界。')
            verify(self.result,*self.inputs())
            if int(float(self.panel.v['combined_intro_last_cue'].get()))!=self.result['last_id']:raise ValueError('片头编号已改变，请重新定位。')
            if not messagebox.askyesno('确认自动分界','确认画面切入位置合适、片头最后一句与正文第一句完整？\n只填写时间并复用已定位配音，不立即导出。',parent=self.win):return
            for key,value in dict(combined_intro_end=self.result['video'],combined_audio_split=self.result['audio'],combined_aligned_srt=self.result['aligned_srt'],combined_alignment_token=self.result['token']).items():self.panel.v[key].set(value)
            self.panel.approved_preview='';self.panel.update();self.status.set('两个分界已填写。片尾仍使用固定原片尾参考定位并确认。')
        except Exception as e:messagebox.showerror('不能应用分界',str(e),parent=self.win)

def show(panel):
    current=getattr(panel,'intro_boundary_dialog',None)
    if current and current.win.winfo_exists():current.win.lift();return
    panel.intro_boundary_dialog=IntroDialog(panel)
