"""Updates run between video jobs; all Tk operations stay on the main thread."""
import json,os,shutil,sys,threading
from pathlib import Path
from tkinter import ttk,messagebox,simpledialog,filedialog
from desktop_update import (APP_VERSION,install_root,read_config,save_config,
                            check_update,download_update,stage_package,activate,version_tuple)
from media import run,Cancelled

class DesktopUpdates:
    def __init__(self,app,parent):
        self.app=app;self.checking=False;self.root=install_root()
        row=ttk.Frame(parent);row.pack(fill='x',pady=(2,4))
        ttk.Label(row,text='桌面版 '+APP_VERSION).pack(side='left')
        ttk.Button(row,text='检查更新',command=lambda:self.check(True)).pack(side='right')
        ttk.Button(row,text='更新设置',command=self.settings).pack(side='right',padx=6)
        app.root.after(2500,lambda:self.check(False))

    def installed(self):
        return bool(os.environ.get('YANGNING_INSTALL_ROOT')) and (self.root/'current.json').is_file()

    def settings(self):
        if self.app.busy:
            messagebox.showinfo('更新设置','请等待当前任务结束。');return
        if not self.installed():
            messagebox.showinfo('安装桌面版','请关闭软件，在解压后的文件夹双击 INSTALL.bat 安装，再从桌面打开。');return
        win=__import__('tkinter').Toplevel(self.app.root);win.title('更新设置');win.geometry('520x240')
        box=ttk.Frame(win,padding=18);box.pack(fill='both',expand=True)
        ttk.Label(box,text='联网更新需要软件发布者提供的固定更新地址。\n设置后，每次启动会检查新版；经你确认后安装。',wraplength=480).pack(anchor='w',pady=8)
        def source():
            try:old=read_config(self.root).get('manifest_url','')
            except Exception:old=''
            value=simpledialog.askstring('固定更新地址','请输入发布者提供的 HTTPS 更新信息地址；留空可关闭联网检查。',initialvalue=old,parent=win)
            if value is not None:
                try:save_config(value.strip(),self.root);messagebox.showinfo('已保存','更新地址已保存。',parent=win)
                except Exception as e:messagebox.showerror('更新地址',str(e),parent=win)
        ttk.Button(box,text='设置固定更新地址',command=source).pack(anchor='w',pady=5)
        ttk.Button(box,text='从更新包升级',command=lambda:self.import_zip(win)).pack(anchor='w',pady=5)
        ttk.Button(box,text='恢复上一个版本',command=lambda:self.rollback(win)).pack(anchor='w',pady=5)

    def check(self,manual=False):
        if self.checking:return
        if not self.installed():
            if manual:messagebox.showinfo('安装桌面版','请先运行 INSTALL.bat，再从桌面打开。')
            return
        if self.app.busy:
            if manual:messagebox.showinfo('正在处理','请等待视频任务结束后更新。')
            return
        try:
            if not read_config(self.root).get('manifest_url'):
                if manual:messagebox.showinfo('尚未接通联网更新','尚未配置发布地址。请在“更新设置”中填写发布者提供的地址。')
                return
        except Exception as e:
            if manual:messagebox.showerror('更新设置',str(e))
            return
        self.checking=True
        def work():
            try:self.app.events.put(('desktop_update','found',check_update(self.root),manual))
            except Exception as e:self.app.events.put(('desktop_update','check_failed',str(e),manual))
        threading.Thread(target=work,daemon=True).start()

    def handle(self,event):
        kind=event[0]
        if kind in ('found','check_failed'):self.checking=False
        if self.app.busy:
            self.app.root.after(500,lambda:self.handle(event));return
        if kind=='check_failed':
            if event[2]:messagebox.showerror('检查更新失败',str(event[1])+'\n当前版本可以继续使用。')
            else:self.app.log_line('自动检查更新未完成：'+str(event[1]))
        elif kind=='found':
            info=event[1]
            if not info:
                if event[2]:messagebox.showinfo('检查更新','当前没有可用的更高版本。')
                return
            if messagebox.askyesno('发现新版',f"新版 {info['version']}\n{info['notes']}\n\n现在下载并安装？当前任务和成片会保留。"):
                self.install(info=info)
        elif kind=='ready':
            self.app.status.set('更新已安装，重新打开桌面软件后生效。')
            messagebox.showinfo('更新完成','更新已安装。请关闭软件，再从桌面打开。\n素材、成片和排版设置已保留。')
        elif kind=='failed':messagebox.showerror('更新失败',str(event[1])+'\n原版本仍可使用。')

    def import_zip(self,win):
        if self.app.busy:return
        path=filedialog.askopenfilename(parent=win,title='选择发布者提供的更新包',filetypes=[('杨宁视频工作室更新包','*.zip')])
        if path:
            win.destroy();self.install(archive=path)

    def install(self,info=None,archive=None):
        if self.app.busy:return
        def work():
            target=None
            try:
                self.app.progress('正在准备更新；不会更改素材和成片…')
                if info:version,target=download_update(info,self.root,cancel=self.app.stop)
                else:
                    version,target=stage_package(archive,self.root)
                    if version_tuple(version)<=version_tuple(APP_VERSION):raise ValueError('请选择比当前版本更高的更新包。')
                if self.app.stop.is_set():raise Cancelled()
                env=os.environ.copy();env['YANGNING_INSTALL_ROOT']=str(self.root)
                # Installed processes already inherit the root used by bootstrap.
                python=self.root/'runtime'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
                self.app.progress('正在检查新版运行环境…')
                run([str(python),str(target/'program'/'bootstrap.py'),'--setup-only'],self.app.stop)
                if self.app.stop.is_set():raise Cancelled()
                activate(self.root,version)
                self.app.events.put(('desktop_update','ready'))
            except Exception as e:
                if target and target.exists():shutil.rmtree(target,ignore_errors=True)
                self.app.events.put(('desktop_update','failed','已取消更新。' if isinstance(e,Cancelled) else str(e)))
        self.app.worker(work)

    def rollback(self,win):
        if self.app.busy:return
        try:
            current=json.loads((self.root/'current.json').read_text())
            old=current.get('previous_version')
            if not old:raise ValueError('尚无可恢复的上一版本。')
            if messagebox.askyesno('恢复上一版',f'下次启动改用 {old}？素材和成片会保留。',parent=win):
                activate(self.root,old);messagebox.showinfo('已恢复','请关闭软件，再从桌面打开。',parent=win)
        except Exception as e:messagebox.showerror('恢复版本',str(e),parent=win)
