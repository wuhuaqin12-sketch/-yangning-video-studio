"""Optional, worker-based fixed-ending setup; candidates never apply themselves."""
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from ending_reference import metadata,save_reference,detect,preview,check_candidate

class ReferenceDialog:
    def __init__(self,panel):
        self.panel=panel;self.app=panel.app;self.root=panel.autosave.parent/'ending_reference'
        self.candidate=None;self.previewed=None
        self.win=tk.Toplevel(self.app.root);self.win.title('固定原片尾参考与自动定位');self.win.geometry('760x510')
        box=ttk.Frame(self.win,padding=16);box.pack(fill='both',expand=True)
        ttk.Label(box,text='① 保存一次原片尾参考（所有语言共用）').pack(anchor='w',pady=6)
        row=ttk.Frame(box);row.pack(fill='x')
        ttk.Button(row,text='选择独立原片尾视频',command=self.choose).pack(side='left')
        ttk.Button(row,text='从当前视频的已确认片尾起点保存',command=self.save_current).pack(side='left',padx=8)
        self.reference_label=tk.StringVar();ttk.Label(box,textvariable=self.reference_label,wraplength=710).pack(anchor='w',pady=8);self.refresh_reference()
        ttk.Label(box,text='参考应包含原片尾的完整画面，不含后来追加的免责声明。\n第一次没有独立原片尾文件时，在主页面填写一次确认好的原片尾开始秒数，再保存参考。\n不同语言只更换新片尾；无需重新设置原片尾参考。',wraplength=710).pack(anchor='w')
        ttk.Separator(box).pack(fill='x',pady=12)
        ttk.Label(box,text='② 在当前完整视频末尾查找原片尾').pack(anchor='w')
        ttk.Button(box,text='自动定位原片尾',command=self.detect).pack(anchor='w',pady=6)
        self.status=tk.StringVar(value='找到候选后不会直接替换。先预览切入点，再确认使用；也可微调候选秒数。')
        ttk.Label(box,textvariable=self.status,wraplength=710).pack(anchor='w',pady=6)
        row=ttk.Frame(box);row.pack(fill='x',pady=6)
        ttk.Label(row,text='候选开始秒（可微调）').pack(side='left');self.seconds=tk.StringVar(value='');ttk.Entry(row,textvariable=self.seconds,width=14).pack(side='left',padx=6)
        self.preview_button=ttk.Button(row,text='预览原片尾切入点',command=self.preview,state='disabled');self.preview_button.pack(side='left',padx=6)
        self.accept_button=ttk.Button(row,text='确认使用此位置',command=self.accept,state='disabled');self.accept_button.pack(side='left')
        ttk.Label(box,text='这里只匹配旧视频里的原片尾，精度约0.13秒，需预览确认。原片尾参考应同画幅、同速度。带免责声明的新片尾不参与匹配，时长可更长、画幅也可不同。',wraplength=710).pack(anchor='w',pady=8)
        ttk.Button(box,text='关闭',command=self.win.destroy).pack(anchor='e')
    def refresh_reference(self):
        try:
            data=metadata(self.root)
            self.reference_label.set(f'已保存原片尾参考，时长 {data["seconds"]:.2f} 秒。' if data else '尚未保存原片尾参考。')
        except Exception as e:self.reference_label.set(str(e))
    def launch(self,kind,fn):
        if self.app.busy:return
        def work():
            try:result=fn()
            except Exception as e:
                self.app.events.put(('ending_reference_event',self,'failed',{'message':str(e)}));return
            self.app.events.put(('ending_reference_event',self,kind,result))
        self.app.worker(work)
    def choose(self):
        if self.app.busy:return
        source=filedialog.askopenfilename(parent=self.win,title='选择未加新免责声明的原片尾视频')
        if source:self.launch('saved',lambda:save_reference(self.root,source,0,self.app.stop,self.app.progress))
    def save_current(self):
        if self.app.busy:return
        try:
            source=self.app.v['video'].get();start=float(self.panel.v['combined_outro_start'].get())
            if not math.isfinite(start) or start<=0:raise ValueError('请先在主页面填入一次确认好的原片尾开始秒数。')
            if not messagebox.askyesno('确认原片尾范围',f'将保存当前视频第 {start:.3f} 秒至结尾的画面作为参考。\n请确认这是原片尾，正文已经结束。',parent=self.win):return
            self.launch('saved',lambda:save_reference(self.root,source,start,self.app.stop,self.app.progress))
        except Exception as e:messagebox.showerror('保存原片尾参考',str(e),parent=self.win)
    def detect(self):
        if self.app.busy:return
        source=self.app.v['video'].get()
        self.candidate=None;self.previewed=None;self.preview_button.state(['disabled']);self.accept_button.state(['disabled'])
        self.status.set('正在查找；当前主页面的片尾位置暂不改变。')
        self.launch('found',lambda:detect(self.root,source,self.app.stop,self.app.progress))
    def preview(self):
        if self.app.busy or not self.candidate:return
        try:
            source=self.app.v['video'].get();start=float(self.seconds.get());candidate=dict(self.candidate)
            self.launch('preview',lambda:preview(self.root,source,candidate,start,self.app.stop))
        except Exception as e:messagebox.showerror('片尾切入点预览',str(e),parent=self.win)
    def receive(self,kind,result):
        if not self.win.winfo_exists():return
        if kind=='failed':
            self.candidate=None;self.previewed=None;self.preview_button.state(['disabled']);self.accept_button.state(['disabled']);self.status.set(result['message'])
            messagebox.showwarning('未应用片尾位置',result['message'],parent=self.win)
        elif kind=='saved':
            self.candidate=None;self.previewed=None;self.refresh_reference();self.preview_button.state(['disabled']);self.accept_button.state(['disabled']);self.status.set('原片尾参考已保存。现在可在完整视频中自动定位。')
        elif kind=='found':
            try:check_candidate(self.root,self.app.v['video'].get(),result)
            except Exception as e:self.status.set(str(e));return
            self.candidate=result;self.seconds.set(f'{result["start"]:.3f}');self.previewed=None
            self.preview_button.state(['!disabled']);self.accept_button.state(['disabled'])
            minutes,seconds=divmod(result['start'],60)
            self.status.set(f'候选位置 {int(minutes):02d}:{seconds:06.3f}，画面相似度 {result["score"]:.1%}（非准确率保证）。尚未应用，请先预览。')
        elif kind=='preview':
            self.previewed=result;self.accept_button.state(['!disabled']);self.status.set('预览已生成：切入点前约3秒、后约4秒。确认正文最后一句没有被切掉，再使用。')
            return result['path']
    def accept(self):
        if self.app.busy:return
        try:
            if not self.candidate or not self.previewed:raise ValueError('请先定位并预览当前切入点。')
            start=float(self.seconds.get())
            check_candidate(self.root,self.app.v['video'].get(),self.candidate)
            if start!=self.previewed['start'] or self.previewed['source_stamp']!=self.candidate['source_stamp'] or self.previewed['reference_id']!=self.candidate['reference_id']:raise ValueError('位置或素材已改变，请重新预览。')
            if not messagebox.askyesno('确认使用定位位置','已看过切入点预览，确认不会截掉正文最后一句？\n确认后只填写原片尾开始位置，不立即导出或修改原文件。',parent=self.win):return
            self.panel.v['combined_outro_start'].set(f'{start:.3f}');self.panel.approved_preview='';self.panel.update();self.status.set('已填写原片尾开始位置。请选择对应语言的新片尾，继续完整视频预览。')
        except Exception as e:messagebox.showerror('不能应用定位位置',str(e),parent=self.win)

def show(panel):
    current=getattr(panel,'ending_reference_dialog',None)
    if current and current.win.winfo_exists():current.win.lift();return
    panel.ending_reference_dialog=ReferenceDialog(panel)
