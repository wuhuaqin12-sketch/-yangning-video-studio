"""Mouse selection of a subtitle band on a source-sized video frame."""
import math,uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from PIL import Image,ImageTk
from media import probe,run,executable,parse_srt
def stamp(path):
    p=Path(path).resolve();s=p.stat()
    return dict(path=str(p),size=s.st_size,modified=s.st_mtime_ns)

def normalized_stream(path,cancel):
    from engine import square_pixel_stream
    video=next(s for s in probe(path,cancel)['streams'] if s['codec_type']=='video');video=square_pixel_stream(video)
    rotation=int(video.get('tags',{}).get('rotate',0))
    for side in video.get('side_data_list',[]):
        if 'rotation' in side:rotation=int(side['rotation'])
    if abs(rotation)%180==90:video['width'],video['height']=video['height'],video['width']
    return video

def frame(source,at,folder,cancel):
    before=stamp(source);info=probe(source,cancel);total=float(info['format']['duration']);at=float(at)
    if not math.isfinite(at) or not 0<=at<total:raise ValueError('取样位置超出视频，请移动滑块。')
    stream=normalized_stream(source,cancel);folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);out=folder/('frame_'+uuid.uuid4().hex+'.png')
    run([executable('ffmpeg'),'-nostdin','-v','error','-y','-ss',str(at),'-i',str(source),'-frames:v','1','-vf',f'scale={stream["width"]}:{stream["height"]},setsar=1',str(out)],cancel)
    if stamp(source)!=before:raise ValueError('取样期间视频已改变，请重新取样。')
    return dict(path=str(out),width=stream['width'],height=stream['height'],at=at,total=total,source_stamp=before)

def rectangle(points,display,source,full_width):
    (x0,y0),(x1,y1)=points;dw,dh=display;sw,sh=source
    left=max(0,min(sw-2,math.floor(min(x0,x1)/dw*sw)));right=min(sw,max(left+2,math.ceil(max(x0,x1)/dw*sw)))
    top=max(0,min(sh-2,math.floor(min(y0,y1)/dh*sh)));bottom=min(sh,max(top+2,math.ceil(max(y0,y1)/dh*sh)))
    return (0,top,sw,bottom-top) if full_width else (left,top,right-left,bottom-top)

class RegionDialog:
    def __init__(self,panel,mode):
        self.panel=panel;self.app=panel.app;self.mode=mode;self.source=self.app.v['video'].get();self.info=None;self.points=None;self.photo=None
        self.win=tk.Toplevel(self.app.root);self.win.title('鼠标框选原中文字幕行（'+('横版' if mode=='landscape' else '竖版')+'）');self.win.geometry(f'{min(960,self.app.root.winfo_screenwidth()-80)}x{min(730,self.app.root.winfo_screenheight()-80)}')
        page=ttk.Frame(self.win,padding=12);page.pack(fill='both',expand=True)
        ttk.Label(page,text='拖动框住中文字和描边所在的上下范围。默认横向全宽；处理时仍只补文字遮罩，不做整块背景修复。',wraplength=900).pack(anchor='w')
        self.canvas=tk.Canvas(page,background='#202020',height=380);self.canvas.pack(fill='both',expand=True,pady=8)
        self.canvas.bind('<ButtonPress-1>',self.down);self.canvas.bind('<B1-Motion>',self.drag)
        self.at=tk.DoubleVar(value=self.initial_time());self.scale=ttk.Scale(page,from_=0,to=max(1,self.at.get()+1),variable=self.at);self.scale.pack(fill='x')
        row=ttk.Frame(page);row.pack(fill='x',pady=4)
        ttk.Label(row,text='取样秒数').pack(side='left');ttk.Entry(row,textvariable=self.at,width=12).pack(side='left',padx=5)
        ttk.Button(row,text='更新画面',command=self.load).pack(side='left');ttk.Button(row,text='上一句',command=lambda:self.cue(-1)).pack(side='left',padx=5);ttk.Button(row,text='下一句',command=lambda:self.cue(1)).pack(side='left')
        ttk.Button(row,text='使用此字幕区域',command=self.accept).pack(side='right')
        self.status=tk.StringVar(value='等待画面加载，之后拖动框选。');ttk.Label(page,textvariable=self.status,wraplength=900).pack(anchor='w',pady=4)
        ttk.Button(page,text='关闭',command=self.win.destroy).pack(anchor='e');self.load()
    def cue_times(self):
        try:return [(a+b)/2 for _,a,b,_ in parse_srt(self.app.v['source_srt'].get())]
        except Exception:return []
    def initial_time(self):
        cues=self.cue_times();index=0
        return cues[min(index,len(cues)-1)] if cues else float(self.panel.v['preview_start'].get())
    def cue(self,step):
        cues=self.cue_times()
        if not cues:return
        current=self.at.get();choices=[x for x in cues if x>current+.01] if step>0 else [x for x in cues if x<current-.01]
        if choices:self.at.set(min(choices) if step>0 else max(choices));self.load()
    def load(self):
        if self.app.busy:messagebox.showinfo('正在处理','请等待当前操作完成。',parent=self.win);return
        try:
            at=self.at.get();source=self.source;folder=self.panel.autosave.parent/'roi_frames'
            def work():
                try:value=frame(source,at,folder,self.app.stop)
                except Exception as e:self.app.events.put(('utility_dialog_event',self,'failed',str(e)));return
                self.app.events.put(('utility_dialog_event',self,'frame',value))
            self.app.worker(work)
        except Exception as e:messagebox.showerror('取样画面',str(e),parent=self.win)
    def receive(self,kind,value):
        if not self.win.winfo_exists():return
        if kind=='failed':self.status.set(str(value));messagebox.showwarning('无法取样',str(value),parent=self.win);return
        self.info=value;self.points=None;self.scale.configure(to=max(0,value['total']-.05));self.at.set(value['at']);self.win.update_idletasks()
        with Image.open(value['path']) as im:
            ratio=min(max(1,self.canvas.winfo_width())/im.width,max(1,self.canvas.winfo_height())/im.height);self.dw=max(2,int(im.width*ratio));self.dh=max(2,int(im.height*ratio));image=im.convert('RGB').resize((self.dw,self.dh),Image.Resampling.LANCZOS)
        self.photo=ImageTk.PhotoImage(image);self.canvas.delete('all');self.canvas.create_image(0,0,image=self.photo,anchor='nw');self.status.set('画面已加载。请拖动框选原中文字幕所在行，再点击“使用此字幕区域”。')
    def down(self,event):
        if self.info:self.points=((max(0,min(self.dw,event.x)),max(0,min(self.dh,event.y))),)*2;self.drag(event)
    def drag(self,event):
        if not self.points:return
        self.points=(self.points[0],(max(0,min(self.dw,event.x)),max(0,min(self.dh,event.y))));self.canvas.delete('selection')
        (x0,y0),(x1,y1)=self.points
        if self.panel.layout_vars[self.mode]['repair_full_width'].get():x0=0;x1=self.dw
        self.canvas.create_rectangle(x0,y0,x1,y1,outline='#FFD400',width=2,tags='selection')
    def accept(self):
        try:
            if not self.info or not self.points:raise ValueError('请先在画面上拖动框选字幕行。')
            if abs(self.points[0][1]-self.points[1][1])<3:raise ValueError('请拖动框住整行文字与描边，不要只点一个位置。')
            if stamp(self.app.v['video'].get())!=self.info['source_stamp']:raise ValueError('视频已更换，请重新取样框选。')
            roi=rectangle(self.points,(self.dw,self.dh),(self.info['width'],self.info['height']),self.panel.layout_vars[self.mode]['repair_full_width'].get())
            values=self.panel.layout_vars[self.mode];values['repair_roi'].set(','.join(map(str,roi)));values['repair_approved'].set('');values['repair_preview_start'].set(str(self.info['at']))
            self.panel.appearance_open.set(True);self.panel.details_open.set(True);self.panel.update();self.status.set('字幕行已选择。可直接生成完整视频；也可先做15秒修复预览。')
        except Exception as e:messagebox.showerror('字幕区域',str(e),parent=self.win)

def show(panel,mode):
    if not panel.app.v['video'].get():messagebox.showinfo('先导入视频','请先导入原视频。',parent=panel.app.root);return
    RegionDialog(panel,mode)
