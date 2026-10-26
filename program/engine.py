import os,json,math,tempfile,threading,hashlib,sys,shutil,subprocess,bisect
from pathlib import Path
from fractions import Fraction
import numpy as np
from scipy.interpolate import PchipInterpolator
from PIL import Image,ImageDraw
from media import executable,run,probe,parse_srt,write_subs,Cancelled
from audio_edit import detect,propose,apply,mapped,import_plan,export_plan,validate_events,pause_summary
VERSION='0.12.9'

def square_pixel_stream(stream):
    """Preserve display geometry when decoding to raw RGB, which has no SAR."""
    result=dict(stream)
    value=stream.get('sample_aspect_ratio')
    if value in (None,'N/A','0:1','1:1'):return result
    try:
        sar=Fraction(value.replace(':','/'))
        if sar<=0:raise ValueError()
    except (ValueError,ZeroDivisionError,AttributeError):
        raise ValueError('无法读取视频像素比例，请检查原视频。')
    width=max(2,2*round(Fraction(stream['width'])*sar/2))
    result.update(width=width,sample_aspect_ratio='1:1',
                  original_width=stream['width'],original_sample_aspect_ratio=value)
    return result

def playback_speed(job):
    try:speed=float(job.get('speed', 1.1))
    except (TypeError,ValueError):raise ValueError('请选择有效的成片倍速。')
    if not math.isfinite(speed) or not 0.5<=speed<=2.0:raise ValueError('成片倍速须在0.5–2.0之间。')
    return speed

def fingerprint(job):
    result={}
    for k in ('video','audio','source_srt','target_srt','audio_reference_srt'):
        if not job.get(k):continue
        p=Path(job[k]).resolve();st=p.stat()
        with p.open('rb') as f:
            b=f.read(65536)
            if st.st_size>65536:f.seek(-65536,2);b+=f.read()
        result[k]={'path':str(p),'size':st.st_size,'mtime_ns':st.st_mtime_ns,'edge_sha256':hashlib.sha256(b).hexdigest()}
    return result

def save_json(path,data):
    temp=Path(str(path)+'.writing');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(path)

def prepare(job,cancel,progress=lambda s:None):
    from workflow import normalize
    job=normalize(job);job['erase_method']='off';job['shots']='';job.pop('_cleanup_profile',None)
    progress('检查字幕、视频与配音；原SRT提供画面时间，配音将重新定位')
    src=parse_srt(job['source_srt']);dst=parse_srt(job['target_srt'])
    if [c[0] for c in src]!=[c[0] for c in dst]:raise ValueError('原视频SRT与配音SRT须逐句对应，编号与数量相同。成品可按句重新分行；不同分句版本请先整理对应关系。')
    vi=probe(job['video'],cancel);v=next(s for s in vi['streams'] if s['codec_type']=='video')
    if int(v['width'])%2 or int(v['height'])%2:raise ValueError('H.264导出须偶数宽高；请先规范化奇数尺寸素材。')
    if any(int(s.get('rotation',0))%360 for s in v.get('side_data_list',[])) or int(v.get('tags',{}).get('rotate',0))%360:raise ValueError('视频有旋转标记，请先按正确方向导出后导入。')
    if v.get('color_transfer') in ('smpte2084','arib-std-b67'):raise ValueError('此版处理SDR素材；检测到HDR，不能无提示改变色彩，请先正规转换为SDR。')
    v=square_pixel_stream(v)
    if v.get('original_sample_aspect_ratio'):
        progress(f"自动校正像素比例：{v['original_width']}×{v['height']} → {v['width']}×{v['height']}，保持原显示比例")
    fps=Fraction(v.get('avg_frame_rate','0/1'));vd=float(v.get('duration',vi['format']['duration']))
    if fps<=0:raise ValueError('无法读取有效的原视频帧率。')
    if src[-1][2]>vd+.2:raise ValueError(f'原视频SRT末尾为{src[-1][2]:.2f}秒，超出原视频{vd:.2f}秒。第三行时间应对应原画面，不要求对应新配音。')
    ai=probe(job['audio'],cancel);a=next(s for s in ai['streams'] if s['codec_type']=='audio');rate=int(a.get('sample_rate',48000));channels=min(2,int(a.get('channels',2)))
    output=Path(job['output']).resolve();output.mkdir(parents=True,exist_ok=True);folder=Path(tempfile.mkdtemp(prefix='YangNing_',dir=output))
    audio=job['audio']
    raw=folder/'original.f32';progress('提取原配音，保留声道/采样率，不调速、不统一改音量')
    args=[executable('ffmpeg'),'-v','error','-y','-i',str(audio),'-vn','-ac',str(channels),'-ar',str(rate)]
    run(args+['-f','f32le',str(raw)],cancel);duration=raw.stat().st_size/(4*channels*rate)
    if job.get('audio_reference_srt'):
        from sound_report import load_reference
        load_reference(job['audio_reference_srt'],duration)
    if job.get('alignment')=='multi':
        from multilingual import align
        dst=align(dst,audio,folder,cancel,progress,job['language'],duration)
    elif dst[-1][2]>duration+.15:raise ValueError('已校对配音SRT超出音频；若只有原视频时间，请选择自动定位。')
    if dst[-1][2]>duration+.1:raise ValueError('定位超出音频时长，停止导出以防截断。')
    silences=detect(raw,rate,channels,cancel);word_rows=json.loads((folder/'words.json').read_text(encoding='utf8'))['words'] if (folder/'words.json').is_file() else None
    events=propose(dst,silences,duration,rate,channels,raw,job.get('trim',True),word_rows,job.get('language'));export_plan(events,folder/'pause_plan.csv')
    if job.get('_pause_override'):export_plan(job['_pause_override'],folder/'pause_plan.csv')
    settings=dict(job);settings.pop('_pause_override',None);settings.pop('_test_model',None)
    save_json(folder/'analysis.json',{'version':VERSION,'publish_settings':job.get('publish_settings') or None,'job':settings,'fingerprint':fingerprint(job),'source':src,'target':dst,'rate':rate,'channels':channels,'audio_duration':duration,'video_duration':vd,'video_stream':v,'fps':str(fps),'silences':silences,'review_note':'停顿为建议值，可试听修改。定位由参考稿约束，不是独立转写或语义正确性认证。'})
    total,active=preview_audio(folder,cancel);progress(pause_summary(duration,total,active,playback_speed(job)))
    if job.get('trim',True) and not active:progress('提示：未剪除空白。未检测到符合安全条件的长静音；静音阈值或配音底噪可能影响检测，请试听核查。')
    progress('分析完成，可编辑停顿表并进行原声/优化A-B试听：'+str(folder))
    return str(folder)

def preview_audio(folder,cancel):
    folder=Path(folder);m=json.loads((folder/'analysis.json').read_text(encoding='utf8'))
    if m.get('version') not in ('0.10.0','0.10.1',VERSION):raise ValueError('旧工程含旧版声音处理，请从原素材重新分析。')
    ev=validate_events(import_plan(folder/'pause_plan.csv'),m['audio_duration']);r,c=m['rate'],m['channels']
    speed=playback_speed(m['job'])
    plan_hash=hashlib.sha256((folder/'pause_plan.csv').read_bytes()+json.dumps([VERSION,speed,m['job'].get('denoise'),m['job'].get('clean_mode','standard'),m['job'].get('mute',True),m['job'].get('audio_profile'),m['job'].get('audio_separate')],sort_keys=True).encode('utf8')).hexdigest()
    cache_path=folder/'audio_versions.json'
    if cache_path.is_file():
        cache=json.loads(cache_path.read_text(encoding='utf8'))
        if cache.get('plan_hash')==plan_hash and all((folder/cache[k]).is_file() for k in ('A','B')) and (folder/'edited.f32').is_file() and (folder/'声音处理明细.txt').is_file():return cache['duration'],ev
    audio_source=folder/'original.f32'
    from voice_clean import enabled,process_wav
    if enabled(m['job']):
        audio_source=folder/'enhanced.f32'
        if not audio_source.exists():
            run([executable('ffmpeg'),'-v','error','-y','-f','f32le','-ar',str(r),'-ac',str(c),'-i',str(folder/'original.f32'),'-c:a','pcm_f32le',str(folder/'original.wav')],cancel)
            process_wav(folder/'original.wav',folder/'enhanced.wav',m['job'],cancel)
            run([executable('ffmpeg'),'-v','error','-y','-i',str(folder/'enhanced.wav'),'-f','f32le',str(audio_source)],cancel)
    total=apply(audio_source,folder/'edited.f32',r,c,ev,cancel)
    original=folder/'A_original.m4a'
    if not original.exists():run([executable('ffmpeg'),'-v','error','-y','-i',m['job']['audio'],'-map','0:a:0','-c:a','aac','-b:a','192k',str(original)],cancel)
    import uuid
    optimized=folder/('B_optimized_'+uuid.uuid4().hex[:10]+'.m4a')
    args=[executable('ffmpeg'),'-v','error','-y','-f','f32le','-ar',str(r),'-ac',str(c),'-i',str(folder/'edited.f32')]
    if speed!=1.0:args+=['-af',f'atempo={speed}']
    run(args+['-c:a','aac','-b:a','192k',str(optimized)],cancel)
    total/=speed
    adjusted=[(i,mapped(a,ev)/speed,mapped(b,ev)/speed,text) for i,a,b,text in m['target']]
    if 'video_stream' in m:
        write_subs(adjusted,folder,m['video_stream']['width'],m['video_stream']['height'],m['job'].get('font') or 'Noto Serif CJK JP',round(m['video_stream']['height']*float(m['job'].get('font_percent',5.6))/100))
    from sound_report import write_report
    sound_meta=json.loads((folder/'声音处理报告.json').read_text(encoding='utf8')) if enabled(m['job']) else {'enabled':False,'mode':'original_audio'}
    if m['job'].get('audio_reference_srt') and not sound_meta.get('reference_path'):
        from sound_report import load_reference
        sound_meta.update(load_reference(m['job']['audio_reference_srt'],m['audio_duration']))
    write_report(folder,sound_meta,m['audio_duration'],events=ev,speed=speed,source=m['job']['audio'],timeline='原配音时间轴',output_duration=total,cues=sound_meta.get('reference_cues',m['target']),subtitle_reference=sound_meta.get('reference_path') or m['job'].get('target_srt',''))
    save_json(cache_path,{'A':original.name,'B':optimized.name,'plan_hash':plan_hash,'duration':total})
    return total,ev

def render_preview(folder,time,cancel):
    folder=Path(folder);m=json.loads((folder/'analysis.json').read_text(encoding='utf8'))
    total,events=preview_audio(folder,cancel);speed=playback_speed(m['job']);t=float(time)
    if not 0<=t<total:raise ValueError('预览时间超出视频。')
    cues=[(i,mapped(a,events)/speed,mapped(b,events)/speed,text) for i,a,b,text in m['target']]
    tx=[0]+[a for i,a,b,text in cues[1:]]+[total];sx=[0]+[a for i,a,b,text in m['source'][1:]]+[m['video_duration']]
    st=float(PchipInterpolator(tx,sx)(t))
    image=folder/'source_preview.png';Image.fromarray(frame_at(m['job']['video'],st,cancel,m['video_stream'])).save(image)
    if not m.get('publish_settings'):return str(image)
    from publish import make_ass,canvas_style
    from publish_style import normalize_style
    opts={**m['publish_settings'],**normalize_style(m['publish_settings'])}
    opts,cw,ch=canvas_style(opts,m['video_stream'])
    vw,vh,vx,vy=make_ass(folder/'publish.ass',cues,opts,m['video_stream'],total,cw,ch)
    if not (folder/'fonts').exists():shutil.copytree(Path(__file__).parent/'fonts',folder/'fonts')
    graph=f'[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[bg];[1:v]scale={vw}:{vh},setsar=1[teacher];[bg][teacher]overlay={vx}:{vy},setpts=PTS+{t}/TB,ass=publish.ass:fontsdir=fonts[v]'
    path=folder/'preview.png'
    if opts['background']:
        run([executable('ffmpeg'),'-v','error','-y','-filter_complex_threads','1','-i',str(Path(opts['background']).resolve()),'-i',str(image),'-filter_complex',graph,'-map','[v]','-frames:v','1',str(path)],cancel,cwd=folder)
    else:
        run([executable('ffmpeg'),'-v','error','-y','-i',str(image),'-vf',f'setpts=PTS+{t}/TB,ass=publish.ass:fontsdir=fonts','-frames:v','1',str(path)],cancel,cwd=folder)
    return str(path)

def frame_at(video,time,cancel,stream=None):
    p=Path(tempfile.mkdtemp(prefix='yn-frame-'))/'frame.png'
    try:
        filters=['-vf',f"scale={stream['width']}:{stream['height']}:flags=lanczos,setsar=1"] if stream and stream.get('original_sample_aspect_ratio') else []
        run([executable('ffmpeg'),'-v','error','-y','-ss',str(max(0,time)),'-i',video]+filters+['-frames:v','1',str(p)],cancel)
        return np.asarray(Image.open(p).convert('RGB')).copy()
    finally:shutil.rmtree(p.parent,ignore_errors=True)


def render(folder,cancel,progress=lambda s:None):
    folder=Path(folder);m=json.loads((folder/'analysis.json').read_text(encoding='utf8'));job=m['job']
    if fingerprint(job)!=m['fingerprint']:raise ValueError('素材在分析后发生变化，请重新分析，避免用旧时间轴导出。')
    total,events=preview_audio(folder,cancel)
    progress(pause_summary(m['audio_duration'],total,events,playback_speed(job)))
    src=m['source'];dst=m['target'];v=m['video_stream'];w,h=v['width'],v['height'];fps=Fraction(m['fps']);f=float(fps);vd=m['video_duration']
    speed=playback_speed(job)
    adjusted=[(i,mapped(a,events)/speed,mapped(b,events)/speed,txt) for i,a,b,txt in dst]
    if any(b<=a or a<0 or b>total+.15 for i,a,b,txt in adjusted):raise ValueError('停顿调整后字幕无效，未导出')
    font=job.get('font') or ('Noto Serif CJK JP' if job.get('language')=='ja' else 'Arial')
    if ',' in font or '\n' in font:raise ValueError('字体名不能包含逗号或换行')
    size=float(job.get('font_percent',5.6))
    if not 1<=size<=15:raise ValueError('字号须为高度的1–15%')
    write_subs(adjusted,folder,w,h,font,round(h*size/100))
    tx=[0]+[a for i,a,b,txt in adjusted[1:]]+[total];sx=[0]+[a for i,a,b,txt in src[1:]]+[vd]
    if any(b<=a for a,b in zip(tx,tx[1:])) or any(b<=a for a,b in zip(sx,sx[1:])):raise ValueError('逐句对应关系无法形成递增时间轴')
    inv=PchipInterpolator(tx,sx);n=math.ceil(total*f)
    # Keep the source bitrate rather than a fixed 480x854 preset. CRF fallback is explicit.
    bitrate=int(v.get('bit_rate') or max(500000,int(m.get('video_bitrate',0))))
    bitrate_known=bool(v.get('bit_rate'))
    vf=[];video_map='0:v:0';ow,oh=w,h
    if m.get('publish_settings'):
        from publish import make_ass,canvas_style
        from publish_style import normalize_style
        opts={**m['publish_settings'],**normalize_style(m['publish_settings'])}
        opts,cw,ch=canvas_style(opts,v)
        vw,vh,vx,vy=make_ass(folder/'publish.ass',adjusted,opts,v,total,cw,ch)
        fonts=Path(__file__).parent/'fonts'
        if not (folder/'fonts').exists():shutil.copytree(fonts,folder/'fonts')
        graph=f'[2:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[bg];[0:v]scale={vw}:{vh},setsar=1[teacher];[bg][teacher]overlay={vx}:{vy}:shortest=1,ass=publish.ass:fontsdir=fonts[v]'
        vf=['-loop','1','-i',str(Path(opts['background']).resolve()),'-filter_complex_threads','1','-filter_complex',graph];video_map='[v]';ow,oh=1080,1920
        if not opts['background']:
            vf=['-vf','ass=publish.ass:fontsdir=fonts'];video_map='0:v:0';ow,oh=w,h
    elif job.get('burn',False):vf=['-vf','ass=subtitles.ass']
    partial=folder/'video.partial.mp4';final=folder/'video.mp4'
    decode_filter=f'fps={fps}'
    if v.get('original_sample_aspect_ratio'):decode_filter+=f',scale={w}:{h}:flags=lanczos,setsar=1'
    decargs=[executable('ffmpeg'),'-v','error','-threads','2','-i',job['video'],'-an','-vf',decode_filter,'-f','rawvideo','-pix_fmt','rgb24','pipe:1']
    encargs=[executable('ffmpeg'),'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}','-r',str(fps),'-i','pipe:0','-i',json.loads((folder/'audio_versions.json').read_text(encoding='utf8'))['B']]+vf+['-map',video_map,'-map','1:a:0','-c:v','libx264','-threads','4','-preset','slow']
    encargs+=['-crf','16'] if m.get('publish_settings') else (['-b:v',str(bitrate),'-maxrate',str(round(bitrate*1.5)),'-bufsize',str(bitrate*2)] if bitrate_known else ['-crf','14'])
    encargs+=['-r',str(fps),'-pix_fmt','yuv420p','-c:a','copy','-t',str(total),'-movflags','+faststart','video.partial.mp4']
    if v.get('color_primaries')=='bt709':encargs[-1:-1]=['-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709']
    flags=0x08000000 if os.name=='nt' else 0;checks=[];repeats=0;max_repeats=0;last_wanted=-1;frame=None;current=-1
    progress(f'按显示尺寸 {w}×{h} / {fps}fps 编码；原视频码率 '+(str(bitrate//1000)+'kbps' if bitrate_known else '未知，使用CRF14'))
    # Isolated per-job output, no re-use of an open output pathname across jobs.
    with (folder/'decoder.log').open('wb') as dl,(folder/'encoder.log').open('wb') as el:
        dec=subprocess.Popen(decargs,stdout=subprocess.PIPE,stderr=dl,creationflags=flags);enc=subprocess.Popen(encargs,stdin=subprocess.PIPE,stderr=el,cwd=folder,creationflags=flags)
        try:
            sample_ids=set(int(t*f) for t in tx if t<total)
            for k in range(n):
                if cancel.is_set():raise Cancelled()
                st=float(inv(min(total,k/f)));wanted=min(round(st*f),max(0,math.floor(vd*f)-1))
                while current<wanted:
                    buf=bytearray();need=w*h*3
                    while len(buf)<need:
                        chunk=dec.stdout.read(need-len(buf))
                        if not chunk:break
                        buf.extend(chunk)
                    if len(buf)!=need:raise RuntimeError('原视频解码提前结束；未补黑帧或静帧。')
                    frame=buf;current+=1
                if frame is None:raise RuntimeError('缺少视频首帧')
                repeats=repeats+1 if wanted==last_wanted else 1;max_repeats=max(max_repeats,repeats);last_wanted=wanted
                fr=np.frombuffer(frame,np.uint8).reshape(h,w,3)
                if k in sample_ids:
                    p=folder/f'check_{k:06}.jpg';Image.fromarray(fr).save(p,quality=90);checks.append(p.name)
                enc.stdin.write(fr.tobytes())
                if k%max(1,round(f*3))==0:progress(f'视频编码 {100*k/n:.0f}%')
            enc.stdin.close()
            import time
            while enc.poll() is None:
                if cancel.is_set():raise Cancelled()
                time.sleep(.1)
            if enc.returncode:raise RuntimeError('编码失败，请查看 encoder.log；未标记为完成。')
        finally:
            for p in (dec,enc):
                if p.poll() is None:p.kill()
                p.wait()
            if dec.stdout:dec.stdout.close()
            if enc.stdin and not enc.stdin.closed:enc.stdin.close()
    progress('完整解码检查、音轨检查及字幕越界检查')
    # ffmpeg may exit 0 despite recoverable corrupt packets: fail on any error output as well.
    validation=run([executable('ffmpeg'),'-v','error','-xerror','-i',str(partial),'-f','null','-'],cancel)
    if validation.strip():raise RuntimeError('完整性检查返回错误：'+validation[-1000:])
    pi=probe(partial,cancel);pv=next(s for s in pi['streams'] if s['codec_type']=='video');pa=next(s for s in pi['streams'] if s['codec_type']=='audio')
    if [pv['width'],pv['height']]!=[ow,oh] or abs(float(Fraction(pv['avg_frame_rate'])-fps))*total>.01:raise RuntimeError('导出分辨率/帧率与目标不一致')
    if pv.get('sample_aspect_ratio') not in (None,'N/A','0:1','1:1'):raise RuntimeError('导出像素比例校验失败')
    if abs(float(pv['duration'])-float(pa['duration']))>max(.10,2/f):raise RuntimeError('音视频结尾时长偏差超限')
    if adjusted[-1][2]>float(pi['format']['duration'])+.05:raise RuntimeError('末条字幕超出导出时长')
    partial.replace(final)
    if m.get('publish_settings'):
        from publish import write_cover,COVER_DEFAULTS
        write_cover({**COVER_DEFAULTS,**opts},folder,cancel,final)
    shutil.copyfile(folder/json.loads((folder/'audio_versions.json').read_text(encoding='utf8'))['B'],folder/'voice.m4a')
    durations={'original_video_seconds':vd,'original_audio_seconds':m['audio_duration'],'output_seconds':float(pi['format']['duration']),'pause_reductions':sum(e['kind']=='cut' and '结尾' not in e['reason'] for e in events),'pause_additions':sum(e['kind']=='add' for e in events),'removed_seconds':sum(e['end']-e['start'] for e in events if e['kind']=='cut'),'added_seconds':sum(e['seconds'] for e in events if e['kind']=='add')}
    report={'version':VERSION,**durations,'resolution':[ow,oh],'fps':str(fps),'video_bitrate':pv.get('bit_rate'),'audio_bitrate':pa.get('bit_rate'),'audio_target_bitrate':192000,'full_decode_passed':True,'timeline_checked':True,'cue_count':len(adjusted),'reference_guided_alignment':job.get('alignment') in ('english','multi'),'visual_review_required':False,'subtitle_removal':False,'max_identical_source_frames':max_repeats,'sample_frames':checks,'warnings':['自动检查不认证译稿与听感，请试听并抽查音画同步。','时间轴同步不等于口型合成。'],'speech_speed':speed,'pause_adjusted_audio_seconds':total*speed,'pitch_preserved':True}
    save_json(folder/'report.json',report)
    (folder/'停顿压缩结果.txt').write_text(pause_summary(m['audio_duration'],total,events,playback_speed(job))+f'\n输出倍速{speed:g}倍，保持音调；请试听并检查同步。\n',encoding='utf-8-sig')
    progress('完成并通过解码检查：'+str(final)+'；'+pause_summary(m['audio_duration'],total,events,playback_speed(job)));return str(folder)

def process(job,cancel,progress=lambda s:None):
    folder=job.get('analysis') or prepare(job,cancel,progress)
    return render(folder,cancel,progress)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('job');p.add_argument('--analyze',action='store_true');a=p.parse_args();j=json.loads(Path(a.job).read_text(encoding='utf-8-sig'))
    print(prepare(j,threading.Event(),print) if a.analyze else process(j,threading.Event(),print))
