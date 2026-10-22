"""Tabbed desktop typography editor, shared by every publishing language."""
import json
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox, colorchooser
from publish import compose, preview_cover, COVER_DEFAULTS
from publish_style import DEFAULTS, normalize_style, save_preset, load_preset, colour


def show(app, open_path):
    if app.busy:return
    job=app.current() or {};folder=Path(job.get('result') or job.get('analysis') or '.')
    defaults=dict(DEFAULTS)
    clean=(folder/'clean_project.json').is_file()
    project=(folder/'analysis.json').is_file() or clean
    saved_style=dict(getattr(app,'pending_style',{}))
    if clean:
        from clean_project import load
        cm=load(folder);saved_style=cm.get('style') or {}
    elif project:
        saved_style=json.loads((folder/'analysis.json').read_text(encoding='utf8')).get('publish_settings') or {}
    try:
        meta=json.loads((folder/'analysis.json').read_text(encoding='utf8'))
        if meta['video_stream']['width']>meta['video_stream']['height']:defaults['title_y']=25
    except (OSError,ValueError,KeyError):meta={}
    values={**defaults,**COVER_DEFAULTS,'video':str(folder/'video.mp4') if (folder/'video.mp4').is_file() else app.v['video'].get(),
        'srt':str(folder/'subtitles.srt') if (folder/'subtitles.srt').is_file() else app.v['source_srt'].get(),
        'background':'','output':job.get('output') or app.v['output'].get(),'preview_time':'1'}
    values.update(saved_style)
    # Project-specific visual assets and title must be selected for each new publication.
    values['background']=''
    values['title']=''
    values['keywords']=''
    if project:
        values['video']=str(folder/'video.mp4') if (folder/'video.mp4').is_file() else (cm['video'] if clean else meta['job']['video'])
        values['srt']=str(folder/'subtitles.srt')
        values['background']=''
        values['title']=''
        values['keywords']=''
    elif meta.get('job',{}).get('burn'):values['video']=''
    win=tk.Toplevel(app.root);win.title('制作发布成片 · 字体 / 颜色 / 重点词');win.geometry('920x700');win.minsize(780,620)
    box=ttk.Frame(win,padding=12);box.pack(fill='both',expand=True)
    ttk.Label(box,text='标题、字幕与重点词样式',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
    ttk.Label(box,text='所有语言统一字号，长句自动分行。保存排版后，回主界面一键导出；预览可选。',wraplength=860).pack(anchor='w',pady=5)
    variables={k:(tk.BooleanVar(value=v) if isinstance(v,bool) else tk.StringVar(value=str(v))) for k,v in values.items()}
    tabs=ttk.Notebook(box);tabs.pack(fill='both',expand=True,pady=5)
    pages={}
    for key,label in [('assets','素材与画面'),('title','标题'),('subtitle','字幕'),('keywords','重点词颜色'),('cover','封面')]:
        page=ttk.Frame(tabs,padding=12);tabs.add(page,text=label);page.columnconfigure(1,weight=1);pages[key]=page
    families=sorted(set(tkfont.families(win))|{'Yuji Boku','Noto Serif CJK JP'})
    def entry(page,row,key,label,kind='text'):
        ttk.Label(page,text=label).grid(row=row,column=0,sticky='w',pady=6,padx=(0,12))
        if kind=='font':widget=ttk.Combobox(page,textvariable=variables[key],values=families,width=32)
        else:widget=ttk.Entry(page,textvariable=variables[key],width=32)
        widget.grid(row=row,column=1,sticky='ew');return widget
    def picker(key):
        selected=filedialog.askdirectory(parent=win) if key=='output' else filedialog.askopenfilename(parent=win,filetypes=([('字幕 SRT / 带时间轴TXT','*.srt *.txt'),('所有文件','*.*')] if key=='srt' else [('所有文件','*.*')]))
        if selected:variables[key].set(selected)
    def colour_row(page,row,key,label):
        entry(page,row,key,label)
        controls=ttk.Frame(page);controls.grid(row=row,column=2,padx=6)
        chip=tk.Label(controls,width=3,relief='sunken');chip.pack(side='left',padx=3)
        def paint(*_):
            try:chip.configure(bg=colour(variables[key].get()))
            except (ValueError,tk.TclError):chip.configure(bg='#808080')
        def choose():
            try:initial=colour(variables[key].get())
            except ValueError:initial='#FFFFFF'
            result=colorchooser.askcolor(initialcolor=initial,parent=win,title=label)
            if result[1]:variables[key].set(result[1].upper())
        variables[key].trace_add('write',paint);paint()
        ttk.Button(controls,text='选颜色',command=choose).pack(side='left')
    page=pages['assets']
    for row,(key,label) in enumerate([('video','源视频（保留原文件）'),('srt','字幕 SRT（导出时自动同步）'),('background','背景图'),('output','成片保存到')]):
        entry(page,row,key,label);ttk.Button(page,text='选择',command=lambda k=key:picker(k)).grid(row=row,column=2,padx=6)
    entry(page,4,'video_width','老师画面最大宽度 %（100＝铺满横向）')
    entry(page,5,'video_height','老师画面最大高度 %')
    ttk.Label(page,text='工程会从源素材直接合成，不使用反复压缩的中间视频。\n一键导出时自动使用本次优化的字幕时间轴。\n本页不擦除已有字幕：源画面有旧字幕时，请先准备干净视频。',wraplength=780).grid(row=6,column=0,columnspan=3,sticky='w',pady=10)
    page=pages['title']
    entry(page,0,'title','标题（可留空）');entry(page,1,'title_font','字体种类','font');colour_row(page,2,'title_color','文字颜色')
    for row,(key,label) in enumerate([('title_font_size','大小（成片像素，默认230）'),('title_x','中心横向 %（50＝居中）'),('title_y','中心纵向 %'),('title_width','区域宽度 %'),('title_outline','描边宽度（像素，0＝无）')],3):entry(page,row,key,label)
    ttk.Label(page,text='日语标题默认 Yuji Boku（佑字 朴）毛笔体。可选本机字体，也可直接输入字体名。',wraplength=780).grid(row=8,column=0,columnspan=3,sticky='w',pady=8)
    page=pages['subtitle']
    entry(page,0,'font','字体种类','font');colour_row(page,1,'subtitle_color','普通文字颜色')
    for row,(key,label) in enumerate([('subtitle_font_size','大小（成片像素，默认47）'),('subtitle_x','中心横向 %（相对老师画面）'),('subtitle_y','中心纵向 %（相对老师画面）'),('subtitle_width','区域宽度 %（相对老师画面）'),('subtitle_height','区域高度 %（相对老师画面）'),('subtitle_outline','描边宽度（像素）')],2):entry(page,row,key,label)
    colour_row(page,8,'outline_color','描边颜色（标题、字幕共用）')
    ttk.Label(page,text='日语字幕默认 Noto Serif CJK JP 明朝体。位置以老师画面计算：0＝左/上，100＝右/下。',wraplength=780).grid(row=9,column=0,columnspan=3,sticky='w',pady=6)
    page=pages['keywords']
    ttk.Label(page,text='仅日语字幕自动识别重点词（红色 / 黄色）；其他语言不自动上色。可手动修改。',wraplength=780).grid(row=0,column=0,columnspan=3,sticky='w',pady=5)
    colour_row(page,1,'keyword_color','未指定颜色的重点词用此颜色')
    word=tk.StringVar();ttk.Label(page,text='新增重点词').grid(row=2,column=0,sticky='w',pady=6)
    ttk.Entry(page,textvariable=word).grid(row=2,column=1,sticky='ew')
    words=tk.Text(page,height=9,wrap='none');words.grid(row=3,column=0,columnspan=3,sticky='nsew',pady=6);words.insert('1.0',values['keywords']);page.rowconfigure(3,weight=1)
    def auto_keywords():
        import re
        from publish_style import parse_keywords
        path=Path(variables['srt'].get())
        if not path.is_file():
            messagebox.showinfo('重点词','请先生成并选择本工程的优化字幕 SRT。',parent=win);return
        if app.v['language'].get() != 'ja':
            words.delete('1.0','end')
            msg.set('当前不是日语：已清空自动重点词颜色，普通字幕保持默认。')
            return
        content=path.read_text(encoding='utf-8-sig',errors='replace')
        red=['真正','本当','真の','重要','核心','关键','本質','真実','解脱','目覚め','本来','大切']
        yellow=['無我','空性','菩提心','慈悲','縁起','涅槃','如来','仏性','悟り','輪廻','般若','金剛経','サマーディ','禅定','無常','般若','涅槃','慈悲']
        # Longest terms first; only literal matches, no fabricated semantic understanding.
        result=[]
        for colour_code,terms in [('#E53935',red),('#FFD54F',yellow)]:
            for term in sorted(set(terms),key=len,reverse=True):
                if (re.search(r'(?<![A-Za-z])'+re.escape(term)+r'(?![A-Za-z])',content,re.I) if term.isascii() else term in content):
                    if not any(term==line.split('=')[0] for line in result):result.append(term+'='+colour_code)
        words.delete('1.0','end');words.insert('1.0','\n'.join(result))
        msg.set(f'已按词库扫描字幕，找到 {len(result)} 个候选重点词。请预览确认，必要时手动修改。')
    ttk.Button(page,text='自动搜索重点词（红 / 黄）',command=auto_keywords).grid(row=7,column=0,columnspan=2,sticky='w',pady=6)

    def add_word():
        value=word.get().strip()
        if not value:return
        try:chosen=colour(variables['keyword_color'].get())
        except ValueError as e:messagebox.showerror('颜色',str(e),parent=win);return
        lines=[s for s in words.get('1.0','end-1c').splitlines() if s.partition('=')[0].strip()!=value]
        lines.append(value+'='+chosen);words.delete('1.0','end');words.insert('1.0','\n'.join(lines));word.set('')
    ttk.Button(page,text='加入 / 更新',command=add_word).grid(row=2,column=2,padx=6)
    ttk.Label(page,text='例如：無我=#E53935    空性=#FFD54F\n不写“=颜色”则使用上方默认重点词颜色；直接编辑或删除对应行即可。颜色仅写入画面，SRT原文与时间不变。',wraplength=780).grid(row=4,column=0,columnspan=3,sticky='w',pady=5)
    ttk.Checkbutton(page,text='拉丁字母忽略大小写',variable=variables['keyword_ignore_case']).grid(row=5,column=0,columnspan=3,sticky='w')
    ttk.Checkbutton(page,text='拉丁词只匹配整词（关闭则可匹配词内文字）',variable=variables['keyword_whole_words']).grid(row=6,column=0,columnspan=3,sticky='w')
    page=pages['cover']
    ttk.Label(page,text='封面随成片单独导出为 cover.png，不占视频时长。',wraplength=780).grid(row=0,column=0,columnspan=3,sticky='w',pady=8)
    cover_name=tk.StringVar(value={'none':'不导出封面','upload':'上传封面图片','frame':'从成片选一帧'}.get(values['cover_mode'],'不导出封面'))
    cover_options={'不导出封面':'none','上传封面图片':'upload','从成片选一帧':'frame'}
    ttk.Label(page,text='封面选项').grid(row=1,column=0,sticky='w')
    cover_box=ttk.Combobox(page,textvariable=cover_name,values=list(cover_options),state='readonly');cover_box.grid(row=1,column=1,sticky='ew',pady=6)
    cover_box.bind('<<ComboboxSelected>>',lambda e:variables['cover_mode'].set(cover_options[cover_name.get()]))
    entry(page,2,'cover_image','封面图片')
    ttk.Button(page,text='选择图片',command=lambda:picker('cover_image')).grid(row=2,column=2,padx=6)
    entry(page,3,'cover_time','成片截帧时间（秒）')
    ttk.Label(page,text='上传的图片按9:16居中填满，边缘可能裁切。\n从成片截帧时会包含这次设置的标题、字幕与重点词颜色。\n可先点“预览 / 导出封面”，再生成整段视频。',wraplength=780).grid(row=4,column=0,columnspan=3,sticky='w',pady=10)
    def cover_preview():
        if app.busy:return
        settings=collect()
        def work():
            try:
                if project and settings['cover_mode']=='frame':raise ValueError('请先用“预览排版”看效果；最终导出时会自动截取封面。')
                app.events.put(('publish_done',preview_cover(settings,app.stop,app.progress)))
            except Exception as e:app.events.put(('error',str(e)))
        msg.set('正在生成封面；完成后自动打开。');app.worker(work)
    ttk.Button(page,text='预览 / 导出封面',command=cover_preview).grid(row=5,column=0,columnspan=2,sticky='w',pady=8)
    line=ttk.Frame(box);line.pack(fill='x',pady=5)
    ttk.Label(line,text='字幕统一字号；长句自动换行，超长字幕分屏显示。').pack(side='left')
    ttk.Label(line,text='预览时间 秒').pack(side='left',padx=(12,3));ttk.Entry(line,textvariable=variables['preview_time'],width=7).pack(side='left')
    msg=tk.StringVar(value='先预览字体、字形、颜色、重点词及位置。字体须包含对应语言的文字。')
    ttk.Label(box,textvariable=msg,wraplength=860).pack(anchor='w',pady=4)
    def collect():
        result={k:v.get() for k,v in variables.items()};result['keywords']=words.get('1.0','end-1c');return result
    def apply_style(style):
        for k,v in style.items():
            if k in variables:variables[k].set(v)
        words.delete('1.0','end');words.insert('1.0',style['keywords'])
    def save():
        try:
            style=normalize_style(collect());path=filedialog.asksaveasfilename(parent=win,defaultextension='.json',initialfile='YangNing_Style.json',filetypes=[('样式文件','*.json')])
            if path:save_preset(path,style);msg.set('样式已保存，下次可直接载入。')
        except Exception as e:messagebox.showerror('保存样式',str(e),parent=win)
    def load():
        path=filedialog.askopenfilename(parent=win,filetypes=[('样式文件','*.json')])
        if not path:return
        try:apply_style(load_preset(path));msg.set('样式已载入；请先预览。')
        except Exception as e:messagebox.showerror('载入样式',str(e),parent=win)
    def go(preview):
        if app.busy:return
        if app.v['language'].get() != 'ja':
            words.delete('1.0','end')
        try:settings=collect();settings.update(normalize_style(settings));settings['auto_fit']=False
        except Exception as e:messagebox.showerror('检查样式',str(e),parent=win);return
        def work():
            try:
                if project:
                    expected=cm['video'] if clean else meta['job']['video']
                    allowed={Path(expected).resolve(),(folder/'video.mp4').resolve()}
                    if Path(settings['video']).resolve() not in allowed:raise ValueError('请使用本工程的视频。')
                    if Path(settings['srt']).resolve()!=(folder/'subtitles.srt').resolve():raise ValueError('请使用本工程的同步字幕。换字幕请重新导入建立工程。')
                    if not Path(settings['background']).is_file():raise ValueError('请先选择背景图。')
                    if clean:
                        from clean_project import load,save,export
                        data=load(folder);data['style']=settings;save(folder/'clean_project.json',data)
                        if preview:app.events.put(('publish_done',export(folder,app.stop,app.progress,preview_time=float(settings['preview_time']))))
                    else:
                        from engine import save_json,render_preview
                        data=json.loads((folder/'analysis.json').read_text(encoding='utf8'));data['publish_settings']=settings;save_json(folder/'analysis.json',data)
                        if preview:app.events.put(('publish_done',render_preview(folder,float(settings['preview_time']),app.stop)))
                    app.progress('排版已保存，可以直接导出；预览可选。')
                else:
                    if not Path(settings['background']).is_file():raise ValueError('请选择背景图。')
                    if preview:app.events.put(('publish_done',compose(settings,app.stop,app.progress,preview=True)))
                saved={k:settings[k] for k in list(DEFAULTS)+list(COVER_DEFAULTS)+['background'] if k in settings}
                app.events.put(('style_saved',saved))
            except Exception as e:app.events.put(('error',str(e)))
        msg.set('处理中，可在主窗口点击停止。完成后自动打开结果。');app.worker(work)
    buttons=ttk.Frame(box);buttons.pack(fill='x',pady=3)
    for label,command in [('恢复默认',lambda:apply_style(defaults)),('保存样式',save),('载入样式',load),('预览排版',lambda:go(True)),('保存排版（不导出整片）',lambda:go(False))]:ttk.Button(buttons,text=label,command=command).pack(side='left',padx=(0,6))
