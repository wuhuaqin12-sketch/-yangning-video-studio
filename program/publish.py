"""Compose a publishable video using final audio/SRT and editable multilingual styles."""
import json, math, re, shutil, tempfile, unicodedata, uuid
from pathlib import Path
from media import executable, run, probe, parse_srt, stamp, Cancelled
from publish_style import (DEFAULTS, normalize_style, clean, units, wrap, fit_text,
                           fit_lines, styled_lines, ass_colour, line_parts)


def layout(opts, stream, w, h):
    scale=min(w*opts['video_width']/100/stream['width'],h*opts['video_height']/100/stream['height'])
    vw=max(2,int(stream['width']*scale)//2*2);vh=max(2,int(stream['height']*scale)//2*2)
    vx=(w-vw)//2;vy=(h-vh)//2
    sw=vw*opts['subtitle_width']/100;sh=vh*opts['subtitle_height']/100
    sx=vx+vw*opts['subtitle_x']/100;sy=vy+vh*opts['subtitle_y']/100
    if sy-sh/2<vy-.01 or sy+sh/2>vy+vh+.01 or sx-sw/2<vx-.01 or sx+sw/2>vx+vw+.01:
        raise ValueError('字幕区域超出老师画面。请移动字幕中心，或减小区域宽度/高度。')
    return vw,vh,vx,vy,sw,sh,sx,sy


def make_ass(path,cues,opts,stream,duration,w,h):
    opts=normalize_style(opts)
    vw,vh,vx,vy,sw,sh,sx,sy=layout(opts,stream,w,h)
    sub_size=opts['subtitle_font_size'] or round(vh*opts['font_percent']/100)
    title_size=opts['title_font_size'] or round(h*opts['title_size']/100)
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{opts['font']},{sub_size},{ass_colour(opts['subtitle_color'])},&H00FFFFFF,{ass_colour(opts['outline_color'])},&H00000000,0,0,0,0,100,100,0,0,1,{opts['subtitle_outline']},0,5,0,0,0,1
Style: Title,{opts['title_font']},{title_size},{ass_colour(opts['title_color'])},&H00FFFFFF,{ass_colour(opts['outline_color'])},&H00000000,0,0,0,0,100,100,0,0,1,{opts['title_outline']},0,5,0,0,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    sizes=[];shrunk=[];split_cues=[];display_cues=[]
    for ident,a,b,text in cues:
        text=clean(text)
        available=min(vh*.40,max(sh,sy+sh/2-vy-8))
        size=round(sub_size)
        # Reflow imported newlines, preserving spaces between Latin words.
        text=re.sub(r'(?<=[A-Za-z0-9])\n(?=[A-Za-z0-9])',' ',text).replace('\n','')
        width_factor=.82 if opts['font']=='Noto Serif CJK JP' else 1.1
        columns=(sw-12)/(size*width_factor)
        if columns<1:
            raise ValueError('字幕区域太窄，连一个字也放不下，请扩大字幕区域宽度。')
        lines=line_parts(text,columns)
        max_lines=min(2,int(available//(size*1.4)))
        if max_lines<1:
            raise ValueError('字幕区域高度不足一行，请扩大区域高度或减小统一字号。')
        pages=[lines[i:i+max_lines] for i in range(0,len(lines),max_lines)]
        if len(pages)>1:split_cues.append(ident)
        # Only cue-level timings are available: distribute pages by text length
        # inside the original adjusted cue; never move its outer boundaries.
        weights=[max(1,sum(units(c) for row in page for _,c in row)) for page in pages]
        total=sum(weights);elapsed=0
        for page,weight in zip(pages,weights):
            start=a+(b-a)*elapsed/total;elapsed+=weight
            end=b if elapsed==total else a+(b-a)*elapsed/total
            sizes.append(size)
            styled=styled_lines(text,page,opts)
            plain='\n'.join(''.join(c for _,c in row) for row in page)
            display_cues.append((start,end,plain))
            header+=f'Dialogue: 1,{stamp(start,True)},{stamp(end,True)},Sub,,0,0,0,,{{\\an2\\pos({sx:.1f},{sy+sh/2:.1f})\\fs{size}\\q2}}{styled}\n'
    actual_title=None
    if opts['title'].strip():
        tx=w*opts['title_x']/100;ty=h*opts['title_y']/100
        tw=min(w*opts['title_width']/100,2*min(tx-w*.025,w*.975-tx))
        if ty<vy:th=2*min(ty-h*.025,vy-h*.0125-ty)
        elif ty>vy+vh:th=2*min(ty-vy-vh-h*.0125,h*.975-ty)
        else:th=2*min(ty-h*.025,h*.975-ty)
        if tw<20 or th<20:raise ValueError('标题区域过小或超出画面，请调整标题中心和宽度。')
        text=clean(opts['title'])
        # Never reject a reasonable title solely because the saved preset has
        # auto_fit=False. First preserve the requested size; if it cannot fit,
        # reduce only the title, without altering subtitle font sizes.
        try:
            size,lines=fit_lines(text,title_size,tw+12,th,False,leading=1.2)
        except ValueError:
            size,lines=fit_lines(text,title_size,tw+12,th,True,leading=1.2)
        actual_title=size
        text=styled_lines(text,lines,opts,highlight=False)
        # libass normalizes this bundled font to its 1448/1000 hhea height.
        # Match the 230px FreeType brush title used in the approved V11 render.
        render_size=round(size*1.448,2) if opts['title_font'].casefold()=='yuji boku' else size
        header+=f'Dialogue: 2,0:00:00.00,{stamp(duration,True)},Title,,0,0,0,,{{\\an5\\pos({tx:.1f},{ty:.1f})\\fs{render_size}\\q2}}{text}\n'
    Path(path).write_text(header,encoding='utf-8-sig')
    report=dict(subtitle_requested_px=sub_size,subtitle_actual_px=sorted(set(sizes)),shrunk_cues=shrunk,
                title_requested_px=title_size,title_actual_px=actual_title,subtitle_center=[sx,sy],video_box=[vx,vy,vw,vh],
                split_cues=split_cues,display_cue_count=len(display_cues),split_timing='proportional_within_adjusted_cue')
    (Path(path).parent/'layout_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    (Path(path).parent/'publish_subtitles.srt').write_text(
        '\n\n'.join(f'{i}\n{stamp(a)} --> {stamp(b)}\n{text}'
                      for i,(a,b,text) in enumerate(display_cues,1))+'\n',encoding='utf-8-sig')
    return vw,vh,vx,vy


COVER_DEFAULTS=dict(cover_mode='none',cover_image='',cover_time=1)


def validate_cover(opts,duration=None):
    if opts['cover_mode'] not in ('none','upload','frame'):raise ValueError('请选择有效的封面模式。')
    if opts['cover_mode']=='upload':
        from PIL import Image
        p=Path(opts.get('cover_image',''))
        if not p.is_file():raise ValueError('请选择封面图片。')
        try:
            with Image.open(p) as image:image.verify()
        except Exception as e:raise ValueError('封面图片无法读取，请选择PNG或JPEG图片。') from e
    if opts['cover_mode']=='frame':
        try:t=float(opts['cover_time'])
        except (TypeError,ValueError):raise ValueError('封面截帧时间须为秒数。')
        if not math.isfinite(t) or t<0 or (duration is not None and t>=duration):raise ValueError('封面截帧时间超出视频范围。')
        opts['cover_time']=t


def write_cover(opts,folder,cancel,video=None):
    if opts['cover_mode']=='none':return None
    path=Path(folder)/'cover.png';partial=Path(folder)/'cover.partial.png'
    if opts['cover_mode']=='upload':
        from PIL import Image,ImageOps
        if cancel.is_set():raise Cancelled()
        with Image.open(opts['cover_image']) as im:
            ImageOps.fit(ImageOps.exif_transpose(im).convert('RGB'),(1080,1920),method=Image.Resampling.LANCZOS).save(partial)
    else:
        run([executable('ffmpeg'),'-v','error','-y','-ss',str(opts['cover_time']),'-threads','2','-i',str(video),'-frames:v','1',str(partial)],cancel)
    partial.replace(path);return str(path)


def preview_cover(settings,cancel,progress=lambda s:None):
    opts={**COVER_DEFAULTS,**settings,**normalize_style(settings)}
    if opts['cover_mode']=='none':raise ValueError('请在封面页选择上传图片或从成片选一帧。')
    validate_cover(opts)
    if opts['cover_mode']=='frame':
        image=Path(compose({**opts,'preview_time':opts['cover_time']},cancel,progress,preview=True))
        target=image.parent/'cover.png';shutil.copyfile(image,target);return str(target)
    if not opts.get('output'):raise ValueError('请选择封面保存位置。')
    folder=Path(opts['output']).resolve()/('cover_'+uuid.uuid4().hex[:10]);folder.mkdir(parents=True)
    return write_cover(opts,folder,cancel)


def compose(settings, cancel, progress=lambda s:None, preview=False):
    opts={**COVER_DEFAULTS,**settings,**normalize_style(settings)}
    for key in ('video','srt','background'):
        if not Path(opts.get(key,'')).is_file():raise ValueError('请选择有效的'+{'video':'优化后视频','srt':'优化后最新SRT','background':'背景图'}[key])
    if not opts.get('output'):raise ValueError('请选择成片保存位置。')
    vp=probe(opts['video'],cancel);stream=next(s for s in vp['streams'] if s['codec_type']=='video')
    if not any(s['codec_type']=='audio' for s in vp['streams']):raise ValueError('优化后视频没有音轨')
    duration=float(stream.get('duration') or vp['format']['duration']);cues=parse_srt(opts['srt'])
    if cues[-1][2]>duration+.1:raise ValueError('字幕超过视频结尾，请选择这次优化导出的最新SRT。')
    validate_cover(opts,duration)
    w,h=1080,1920
    out=Path(opts['output']).resolve();out.mkdir(parents=True,exist_ok=True)
    folder=out/('publish_'+uuid.uuid4().hex[:10]);folder.mkdir()
    try:
        vw,vh,vx,vy=make_ass(folder/'publish.ass',cues,opts,stream,duration,w,h)
        fonts=Path(__file__).resolve().parent/'fonts'
        if fonts.is_dir():shutil.copytree(fonts,folder/'fonts')
        ass='ass=publish.ass'+(':fontsdir=fonts' if (folder/'fonts').is_dir() else '')
        graph=(f'[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1[bg];'
               f'[1:v]scale={vw}:{vh},setsar=1[teacher];'
               f'[bg][teacher]overlay={vx}:{vy}:shortest=1,{ass}[v]')
        args=[executable('ffmpeg'),'-v','error','-y','-filter_complex_threads','1','-threads','1','-loop','1','-framerate',stream['avg_frame_rate'],'-i',str(Path(opts['background']).resolve()),'-threads','2','-i',str(Path(opts['video']).resolve()),'-filter_complex',graph,'-map','[v]']
        report=json.loads((folder/'layout_report.json').read_text(encoding='utf8'))
        if preview:
            t=float(opts.get('preview_time',cues[0][1]+.1))
            if not math.isfinite(t) or not 0<=t<duration:raise ValueError('预览时间超出视频范围')
            progress('正在预览字体、颜色、重点词与位置…')
            run(args+['-ss',str(t),'-frames:v','1','preview.png'],cancel,cwd=folder)
            return str(folder/'preview.png')
        progress('正在合成背景、标题和最新字幕（1080×1920）…')
        run(args+['-map','1:a:0','-c:v','libx264','-threads','4','-crf','16','-preset','medium','-pix_fmt','yuv420p','-c:a','copy','-t',str(duration),'-movflags','+faststart','publish.partial.mp4'],cancel,cwd=folder)
        progress('正在检查完整成片和音轨…')
        check=run([executable('ffmpeg'),'-v','error','-xerror','-threads','2','-i',str(folder/'publish.partial.mp4'),'-f','null','-'],cancel)
        if check.strip():raise RuntimeError(check[-1000:])
        info=probe(folder/'publish.partial.mp4',cancel)
        a=next(s for s in info['streams'] if s['codec_type']=='audio');v=next(s for s in info['streams'] if s['codec_type']=='video')
        if abs(float(v['duration'])-duration)>.15 or abs(float(a['duration'])-float(v['duration']))>.15:raise RuntimeError('成片时长或音画结尾检查未通过')
        (folder/'publish.partial.mp4').replace(folder/'publish.mp4')
        shutil.copyfile(opts['srt'],folder/'subtitles.srt')
        (folder/'publish_settings.json').write_text(json.dumps(opts,ensure_ascii=False,indent=2),encoding='utf8')
        cover=write_cover(opts,folder,cancel,video=folder/'publish.mp4')
        if cover:progress('封面已导出：'+cover)
        progress('发布成片已完成：'+str(folder/'publish.mp4'))
        return str(folder/'publish.mp4')
    except Exception:
        (folder/'publish.partial.mp4').unlink(missing_ok=True)
        raise
