"""Source-backed preview projects. No full MP4 is made until explicit export."""
import json, hashlib, shutil, tempfile, uuid, math
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from media import probe, run, executable, parse_srt, stamp, Cancelled

def save(path,obj):
    p=Path(path);tmp=p.with_suffix('.writing');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(p)

def identity(path):
    p=Path(path).resolve();s=p.stat()
    return [str(p),s.st_size,s.st_mtime_ns]

def load(folder,check=True):
    m=json.loads((Path(folder)/'clean_project.json').read_text(encoding='utf8'))
    if m.get('version')!='0.10.0':raise ValueError('旧工程含声音处理，请用原素材重新制作；旧文件保留。')
    if check:
        for k,v in m['sources'].items():
            if identity(v[0])!=v:raise ValueError('源素材已变化，请重新生成预览。')
    return m

def prepare(job,cancel,progress=lambda s:None,make_previews=True):
    video=Path(job['video']).resolve()
    if not video.is_file():raise ValueError('请先选择视频。')
    source=Path(job.get('audio') or video).resolve()
    vi=probe(video,cancel);v=next(s for s in vi['streams'] if s['codec_type']=='video')
    duration=float(v.get('duration') or vi['format']['duration'])
    if v.get('color_transfer') in ('smpte2084','arib-std-b67'):raise ValueError('此版不直接处理HDR，请先转换成SDR。')
    ai=probe(source,cancel);a=next((s for s in ai['streams'] if s['codec_type']=='audio'),None)
    if not a:raise ValueError('所选素材没有声音。')
    if abs(float(a.get('duration') or ai['format']['duration'])-duration)>.2:
        raise ValueError('配音与视频时长不同，请使用“配音与停顿优化”，先完成音画匹配。')
    srt=job.get('source_srt');cues=parse_srt(srt) if srt else []
    if cues and cues[-1][2]>duration+.1:raise ValueError('字幕超过视频时长，请选择当前视频对应的SRT。')
    out=Path(job['output']).resolve();out.mkdir(parents=True,exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='试听工程_',dir=out));progress('提取原声；保留源视频，不导出整片…')
    rate=int(a.get('sample_rate',48000));channels=min(2,int(a.get('channels',1)))
    run([executable('ffmpeg'),'-v','error','-y','-i',str(source),'-vn','-ar',str(rate),'-ac',str(channels),'-c:a','pcm_f32le',str(folder/'original.wav')],cancel)
    from voice_clean import process_wav
    report=process_wav(folder/'original.wav',folder/'enhanced.wav',job,cancel,progress)
    separation=report.get('separation')
    progress('检查自然停顿；剪短时同步画面和字幕…')
    sources={'video':identity(video),'audio':identity(source)}
    if srt:sources['srt']=identity(srt)
    from auto_silence import propose
    automatic=propose(folder/'original.wav',cues) if job.get('auto_cut',True) else []
    progress(f'自动剪短{len(automatic)}处长空白；保留自然停顿。')
    m=dict(version='0.10.0',video=str(video),audio=str(source),sources=sources,
           stream=v,duration=duration,rate=rate,channels=channels,cues=cues,edits=[],auto_edits=automatic,separation=separation,
           style=None,denoise=report,preview_start=0,preview_end=min(15,duration),
           note='原始PCM始终保留；声音处理按明确开关执行，不自动删词。')
    save(folder/'clean_project.json',m);rebuild(folder,cancel)
    if make_previews:
        preview(folder,cancel,0,min(15,duration))
        progress('生成可选的短视频预览…')
        export(folder,cancel,progress,preview_range=(0,min(8,duration)))
    progress('素材已准备，可以直接导出。')
    return str(folder)

def validate_edits(edits,duration):
    result=[]
    for e in edits:
        a,b=float(e['start']),float(e['end']);kind=e['kind']
        if not math.isfinite(a+b) or not 0<=a<b<=duration or kind not in ('mute','cut'):raise ValueError('修改时间须在视频范围内，且结束晚于开始。')
        result.append(dict(start=a,end=b,kind=kind))
    ordered=sorted(result,key=lambda x:x['start'])
    if any(a['end']>b['start'] for a,b in zip(ordered,ordered[1:])):raise ValueError('修改范围不能重叠。请合并范围或撤销上一处。')
    return result

def mapped(t,cuts):
    return t-sum(max(0,min(t,e['end'])-e['start']) for e in cuts)

def rebuild(folder,cancel):
    folder=Path(folder);m=load(folder);edits=validate_edits(m['edits'],m['duration'])
    from auto_silence import merge_cuts
    r,x=wavfile.read(folder/'enhanced.wav');x=x.copy();cuts=merge_cuts(m.get('auto_edits',[])+[e for e in edits if e['kind']=='cut'])
    for e in edits:
        if cancel.is_set():raise Cancelled()
        a,b=round(e['start']*r),min(len(x),round(e['end']*r));k=min(round(r*.005),a,len(x)-b)
        if e['kind']=='mute':
            x[a:b]=0
            if k:
                shape=(k,)+(1,)*(x.ndim-1)
                x[a-k:a]*=np.linspace(1,0,k).reshape(shape);x[b:b+k]*=np.linspace(0,1,k).reshape(shape)
    for e in reversed(cuts):
        a,b=round(e['start']*r),round(e['end']*r)
        # Fade within retained samples, without changing the exact cut duration.
        k=min(round(r*.005),a,len(x)-b)
        if k:
            shape=(k,)+(1,)*(x.ndim-1)
            x[a-k:a]*=np.linspace(1,0,k).reshape(shape);x[b:b+k]*=np.linspace(0,1,k).reshape(shape)
        x=np.concatenate([x[:a],x[b:]])
    if not len(x):raise ValueError('不能剪掉整段视频。')
    wavfile.write(folder/'edited.wav',r,x)
    adjusted=[]
    for _,a,b,text in m['cues']:
        a,b=mapped(a,cuts),mapped(b,cuts)
        if b-a>.001:adjusted.append((len(adjusted)+1,a,b,text))
    (folder/'subtitles.srt').write_text('\n\n'.join(f'{i}\n{stamp(a)} --> {stamp(b)}\n{text}' for i,a,b,text in adjusted)+'\n',encoding='utf-8-sig')
    m['adjusted']=adjusted;m['cuts']=cuts;m['output_duration']=mapped(m['duration'],cuts)
    save(folder/'clean_project.json',m)
    return m

def edit(folder,start,end,kind,cancel):
    folder=Path(folder);m=load(folder);candidate=m['edits']+[dict(start=start,end=end,kind=kind)]
    m['edits']=validate_edits(candidate,m['duration']);save(folder/'clean_project.json',m)
    return rebuild(folder,cancel)

def undo(folder,cancel,all_edits=False):
    folder=Path(folder);m=load(folder)
    # Rebuild from the source enhancement, so undo never accumulates edits.
    m['edits']=[] if all_edits else m['edits'][:-1];save(folder/'clean_project.json',m)
    return rebuild(folder,cancel)

def preview(folder,cancel,start=0,end=15):
    folder=Path(folder);m=rebuild(folder,cancel);start=float(start);end=float(end)
    if not math.isfinite(start+end) or not 0<=start<end<=m['duration']+.001:raise ValueError('请填写有效的试听开始和结束秒数。')
    if end-start>60:raise ValueError('每次试听最多60秒，请缩短范围。')
    bstart,bend=mapped(start,m['cuts']),mapped(end,m['cuts'])
    if bend-bstart<.01:raise ValueError('这段已全部剪掉，请把试听范围扩大到前后语句。')
    for source,dest,a,b in [('original.wav','试听_原声.m4a',start,end),('edited.wav','试听_处理后.m4a',bstart,bend)]:
        run([executable('ffmpeg'),'-v','error','-y','-i',str(folder/source),'-ss',str(a),'-t',str(b-a),'-c:a','aac','-b:a','192k',str(folder/dest)],cancel)
    m.update(preview_start=start,preview_end=end);save(folder/'clean_project.json',m)
    return str(folder/'试听_处理后.m4a')

def video_graph(m):
    cuts=m.get('cuts',[])
    if not cuts:return '[0:v]setpts=PTS-STARTPTS[teacher]'
    kept=[];t=0
    for e in cuts:
        if e['start']>t:kept.append((t,e['start']))
        t=e['end']
    if t<m['duration']:kept.append((t,m['duration']))
    graph='[0:v]split='+str(len(kept))+''.join(f'[s{i}]' for i in range(len(kept)))+';'
    graph+=';'.join(f'[s{i}]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]' for i,(a,b) in enumerate(kept))
    return graph+';'+''.join(f'[v{i}]' for i in range(len(kept)))+f'concat=n={len(kept)}:v=1:a=0[teacher]'

def export(folder,cancel,progress=lambda s:None,preview_time=None,preview_range=None):
    from publish_style import normalize_style
    from publish import make_ass,write_cover,COVER_DEFAULTS,validate_cover
    folder=Path(folder);m=rebuild(folder,cancel);duration=m['output_duration'];style=m.get('style')
    out=folder/('preview.mp4' if preview_range is not None else 'preview.png' if preview_time is not None else 'video.partial.mp4')
    args=[executable('ffmpeg'),'-v','error','-y','-filter_complex_threads','1','-i',m['video'],'-i',str(folder/'edited.wav')]
    graph=video_graph(m);styled=bool(style)
    if styled:
        if not m['adjusted']:raise ValueError('排版需要当前视频对应的字幕SRT。')
        opts={**COVER_DEFAULTS,**style,**normalize_style(style)}
        validate_cover(opts,duration)
        if not Path(opts['background']).is_file():raise ValueError('请选择背景图片。')
        vw,vh,vx,vy=make_ass(folder/'publish.ass',m['adjusted'],opts,m['stream'],duration,1080,1920)
        if not (folder/'fonts').exists():shutil.copytree(Path(__file__).parent/'fonts',folder/'fonts')
        args+=['-loop','1','-i',str(Path(opts['background']).resolve())]
        graph+=f';[2:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[bg];[teacher]scale={vw}:{vh},setsar=1[scaled];[bg][scaled]overlay={vx}:{vy}:shortest=1,ass=publish.ass:fontsdir=fonts[v]'
    else:graph+=';[teacher]null[v]'
    if preview_range is not None:
        start,end=map(float,preview_range)
        if not 0<=start<end<=m['duration']+.001 or end-start>30:raise ValueError('短视频预览请选0–30秒范围，时间须在原视频内。')
        a,b=mapped(start,m['cuts']),mapped(end,m['cuts'])
        if b-a<.01:raise ValueError('这段已剪掉，请扩大预览范围。')
        run(args+['-filter_complex',graph,'-map','[v]','-map','1:a:0','-ss',str(a),'-t',str(b-a),'-c:v','libx264','-threads','4','-preset','ultrafast','-crf','24','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-movflags','+faststart',str(out)],cancel,cwd=folder)
        return str(out)
    if preview_time is not None:
        t=float(preview_time)
        if not 0<=t<duration:raise ValueError('预览时间超出视频。')
        run(args+['-filter_complex',graph,'-map','[v]','-ss',str(t),'-frames:v','1',str(out)],cancel,cwd=folder)
        return str(out)
    progress('从源视频最终导出；使用已试听的声音处理设置…')
    if not m['cuts'] and not styled:
        encoding=['-map','0:v:0','-map','1:a:0','-c:v','copy']
    else:encoding=['-filter_complex',graph,'-map','[v]','-map','1:a:0','-c:v','libx264','-threads','4','-preset','medium','-crf','16','-pix_fmt','yuv420p','-fps_mode','vfr']
    run(args+encoding+['-c:a','aac','-b:a','192k','-t',str(duration),'-movflags','+faststart',str(out)],cancel,cwd=folder)
    check=run([executable('ffmpeg'),'-v','error','-xerror','-threads','2','-i',str(out),'-f','null','-'],cancel)
    if check.strip():raise RuntimeError('成片检查未通过：'+check[-1000:])
    info=probe(out,cancel);v=next(s for s in info['streams'] if s['codec_type']=='video');a=next(s for s in info['streams'] if s['codec_type']=='audio')
    if abs(float(v['duration'])-duration)>.16 or abs(float(v['duration'])-float(a['duration']))>.16:raise RuntimeError('导出时长或同步检查未通过。')
    out.replace(folder/'video.mp4')
    if styled:write_cover(opts,folder,cancel,folder/'video.mp4')
    save(folder/'export_report.json',dict(source=m['video'],duration=duration,video_stream_copied=not m['cuts'] and not styled,video_encodes=1 if m['cuts'] or styled else 0,full_decode_passed=True,video_bitrate=v.get('bit_rate'),fps=v.get('avg_frame_rate')))
    progress('已导出：'+str(folder/'video.mp4'))
    return str(folder/'video.mp4')
