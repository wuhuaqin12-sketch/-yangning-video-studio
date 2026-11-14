"""Optional cover/opening/body/ending workflow over the existing alignment engine.

Speech generation is intentionally absent. Original inputs are read-only.
"""
import json,math,os,shutil,tempfile,uuid
from pathlib import Path
from PIL import Image
from media import executable,run,probe,parse_srt,stamp,Cancelled
from desktop_update import atomic_json
from project_vnext import normalize,processing_key,unique_output,file_digest

def seconds(path,cancel):return float(probe(path,cancel)['format']['duration'])
def write_srt(path,cues):
    Path(path).write_text('\n\n'.join(f'{i}\n{stamp(a)} --> {stamp(b)}\n{text}' for i,a,b,text in cues)+'\n',encoding='utf-8-sig')
def ff(args,cancel,cwd=None):return run([executable('ffmpeg'),'-nostdin','-v','error','-y',*map(str,args)],cancel,cwd)
def valid_file(value,label):
    if not value or not Path(value).is_file():raise ValueError('请选择有效的'+label)
    return str(Path(value).resolve())

def aligned(job,folder,cancel,progress):
    """Use existing engine unchanged; reuse completed sound/timeline computation."""
    from engine import prepare,render,fingerprint
    from workflow import normalize as normalize_job
    j=normalize_job({**job,'publish_settings':{},'burn':False})
    key=processing_key(j);cache=folder/'processing_cache'/key;cache.mkdir(parents=True,exist_ok=True)
    index=cache/'index.json'
    if index.is_file():
        record=json.loads(index.read_text());candidate=Path(record['folder'])
        if (candidate/'video.mp4').is_file() and (candidate/'report.json').is_file():
            m=json.loads((candidate/'analysis.json').read_text())
            if m['fingerprint']==fingerprint(j):
                progress('复用已完成的配音处理与逐句音画匹配')
                return candidate
    j['output']=str(cache)
    result=Path(prepare(j,cancel,progress));render(result,cancel,progress)
    atomic_json(index,{'folder':str(result),'key':key})
    return result

def target_cues(srt,audio,target,folder,language,cancel,progress):
    refs=parse_srt(srt)
    if target:
        cues=parse_srt(target)
        if [c[0] for c in refs]!=[c[0] for c in cues]:raise ValueError('片头原字幕与配音字幕编号不对应。')
    else:
        from multilingual import align
        folder.mkdir(parents=True,exist_ok=True)
        cues=align(refs,audio,folder,cancel,progress,language,seconds(audio,cancel))
    if cues[-1][2]>seconds(audio,cancel)+.03:raise ValueError('片头配音字幕超出音频时长。')
    return refs,cues

def opening(job,p,folder,cancel,progress):
    source=valid_file(p['intro_video'],'片头视频')
    if p['intro_mode']=='original':return source,[]
    audio=valid_file(p['intro_audio'],'片头配音');srt=valid_file(p['intro_srt'],'片头SRT')
    background=None
    if not p['intro_clean_audio']:
        token=file_digest(source)+':'+p['intro_separation_model']
        if p['intro_separation_approved']!=token:raise ValueError('片头中文与音乐仍混合时，请先执行20秒背景声分离试听并确认结果，或提供已去人声的片头。当前未经听审的分离不能直接导出。')
        from background_separation import separate
        sep=folder/'full_background';sep.mkdir(exist_ok=True)
        background=separate(source,sep,cancel,progress,p['intro_separation_model'])
        if abs(seconds(background,cancel)-seconds(source,cancel))>.12:raise ValueError('分离后的音乐长度与片头不符，未截断原声。')
    refs,cues=target_cues(srt,audio,p['intro_target_srt'],folder/'intro_alignment',job['language'],cancel,progress)
    duration=seconds(source,cancel);voice_duration=seconds(audio,cancel)
    # Cut ONLY at actual aligned phrase gaps, then place intact phrases on source
    # scene anchors. Delays can grow; speech is never sped up or truncated.
    boundaries=[0]+[(cues[i-1][2]+cues[i][1])/2 for i in range(1,len(cues))]+[voice_duration]
    segments=[];placed=[];previous=0
    for n,(ref,cue) in enumerate(zip(refs,cues)):
        a,b=boundaries[n:n+2];start=max(ref[1]-(cue[1]-a),previous+.08 if n else 0)
        end=start+b-a
        if end>duration+.02:raise ValueError(f'片头第{ref[0]}句无法完整放入片头，请提供更长片头或调整停顿；未截断配音。')
        segments.append((a,b,start));placed.append((ref[0],start+cue[1]-a,start+cue[2]-a,ref[3]));previous=end
    # Lower background music only while narration is present, preserving the
    # original full-length music track; no global mute or fake denoising.
    music_index=2 if background else 0
    filters=[f'[{music_index}:a]aresample=48000,aformat=channel_layouts=stereo[music]',f'[1:a]asplit={len(segments)}'+''.join(f'[a{i}]' for i in range(len(segments)))]
    for i,(a,b,start) in enumerate(segments):filters.append(f'[a{i}]atrim=start={a}:end={b},asetpts=PTS-STARTPTS,adelay={round(start*1000)}:all=1[v{i}]')
    filters.append(''.join(f'[v{i}]' for i in range(len(segments)))+f'amix=inputs={len(segments)}:normalize=0:duration=longest,apad=whole_dur={duration},atrim=duration={duration},asplit=2[voice][key]')
    filters.append('[music][key]sidechaincompress=threshold=0.025:ratio=5:attack=20:release=300[duck]')
    filters.append('[duck][voice]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89:level=0:latency=1[mix]')
    dest=folder/'intro_mixed.mp4'
    inputs=['-i',source,'-i',audio]+(['-i',background] if background else [])
    ff([*inputs,'-filter_complex',';'.join(filters),'-map','0:v:0','-map','[mix]','-c:v','copy','-c:a','aac','-b:a','192k',dest],cancel)
    if abs(seconds(dest,cancel)-duration)>.15:raise RuntimeError('片头混音改变了时长。')
    write_srt(folder/'intro_aligned.srt',placed)
    return str(dest),placed

def split_combined(job,p,folder,cancel,progress):
    """Explicit boundaries; never infer the ending from the last SRT cue."""
    j=dict(job);p=json.loads(json.dumps(p));source=valid_file(j['video'],'完整视频')
    duration=seconds(source,cancel);tail=p['combined_outro_start'];head=p['combined_intro_end']
    if not 0<tail<duration:raise ValueError('完整视频模式必须明确指定片尾开始秒数，不能使用SRT末尾猜测。')
    if head>=tail:raise ValueError('片头结束时间必须早于片尾开始时间。')
    if p['outro_enabled'] and p['outro_video']:raise ValueError('完整视频已有受保护片尾，不能同时再导入独立片尾；请关闭其中一个，避免重复。')
    refs=parse_srt(j['source_srt'])
    if any(a<tail<b for _,a,b,_ in refs):raise ValueError('指定片尾边界穿过一句字幕，请调整边界。')
    def cut(name,a,b):
        out=folder/name
        ff(['-i',source,'-ss',a,'-t',b-a,'-map','0:v:0','-map','0:a:0?','-c:v','libx264','-preset','fast','-crf','18','-c:a','aac',out],cancel)
        return str(out)
    p.update(outro_enabled=True,outro_video=cut('protected_ending.mp4',tail,duration))
    if head:
        split=p['combined_audio_split']
        if not 0<split<seconds(j['audio'],cancel):raise ValueError('完整视频含替换配音片头时，请指定合并配音中的片头结束秒数（可先自动定位预览）。')
        if any(a<head<b for _,a,b,_ in refs):raise ValueError('片头边界穿过字幕。')
        first=[c for c in refs if c[2]<=head];body=[c for c in refs if head<=c[1]<tail]
        if not first or not body:raise ValueError('片头或正文字幕为空，请检查边界。')
        write_srt(folder/'combined_intro.srt',[(i+1,a,b,t) for i,(_,a,b,t) in enumerate(first)])
        write_srt(folder/'combined_body.srt',[(i+1,a-head,b-head,t) for i,(_,a,b,t) in enumerate(body)])
        for name,a,b in [('combined_intro.wav',0,split),('combined_body.wav',split,seconds(j['audio'],cancel))]:
            ff(['-i',j['audio'],'-ss',a,'-t',b-a,'-c:a','pcm_s16le',folder/name],cancel)
        p.update(intro_enabled=True,intro_video=cut('combined_opening.mp4',0,head),intro_audio=str(folder/'combined_intro.wav'),intro_srt=str(folder/'combined_intro.srt'),intro_target_srt='',intro_mode='music_voice')
        j.update(video=cut('combined_body.mp4',head,tail),audio=str(folder/'combined_body.wav'),source_srt=str(folder/'combined_body.srt'),target_srt='',alignment='auto')
    else:
        body=[c for c in refs if c[1]<tail]
        write_srt(folder/'combined_body.srt',body)
        j.update(video=cut('combined_body.mp4',0,tail),source_srt=str(folder/'combined_body.srt'))
    return j,p

def choose_modes(p,total,source_stream):
    if p['output_mode']=='both':return ['landscape','portrait']
    if p['output_mode']!='auto':return [p['output_mode']]
    # Recommendation only. Manual output mode always overrides it.
    return ['portrait'] if total<=180 and source_stream['height']>=source_stream['width'] else ['landscape']

def repair_key(source,roi,temporal=True):return file_digest(source)+':'+roi+':'+str(bool(temporal))

def repair(source,layout,folder,cancel,preview=False,start=0,length=15):
    if not layout['remove_chinese']:return source
    if layout.get('clean_video'):
        clean=valid_file(layout['clean_video'],'无字幕原片')
        if abs(seconds(clean,cancel)-seconds(source,cancel))>.1:raise ValueError('无字幕原片时长与当前段不一致，请先正确匹配。')
        return clean
    roi=layout.get('repair_roi','').strip()
    try:x,y,w,h=map(int,roi.split(','))
    except Exception:raise ValueError('清除原中文字幕需要先设置区域 x,y,宽,高，并生成15秒修复预览。')
    stream=next(s for s in probe(source,cancel)['streams'] if s['codec_type']=='video')
    if min(x,y)<1 or min(w,h)<2 or x+w>=stream['width']-1 or y+h>=stream['height']-1:raise ValueError('字幕修复区域必须在原视频内部，不能裁掉老师画面。')
    if not preview and layout.get('repair_approved')!=repair_key(source,roi,layout.get('repair_temporal',True)):raise ValueError('横版原中文字幕修复尚未确认。请先看15秒区域修复预览；低资源方法可能模糊或闪烁，不能承诺AI级还原。')
    name=('repair_preview_' if preview else 'repaired_')+uuid.uuid4().hex[:8]+'.mp4';out=folder/name
    args=['-i',source]
    if preview:args+=['-ss',start,'-t',length]
    if layout.get('repair_temporal',True):
        graph=f'[0:v]split=2[base][work];[work]delogo=x={x}:y={y}:w={w}:h={h}:show=0,crop={w}:{h}:{x}:{y},tmix=frames=3:weights=1 2 1[patch];[base][patch]overlay={x}:{y}[v]'
        filters=['-filter_complex_threads','1','-filter_complex',graph,'-map','[v]','-map','0:a:0?']
    else:filters=['-vf',f'delogo=x={x}:y={y}:w={w}:h={h}:show=0']
    ff([*args,*filters,'-c:v','libx264','-preset','fast','-crf','18','-c:a','copy',out],cancel)
    return str(out)

def compose_segment(source,cues,style,mode,p,folder,cancel,burn,label,repair_chinese=False):
    from publish import make_ass
    from publish_style import normalize_style
    width,height=(1920,1080) if mode=='landscape' else (1080,1920)
    if repair_chinese:source=repair(source,p['layouts'][mode],folder,cancel)
    stream=next(s for s in probe(source,cancel)['streams'] if s['codec_type']=='video')
    duration=seconds(source,cancel)
    opts=normalize_style(style or {})
    opts.update(subtitle_area='video' if mode=='landscape' else 'below_video',subtitle_offset_y=p['layouts'][mode]['subtitle_offset_y'])
    if mode=='landscape':
        opts.update(video_width=100,video_height=100,subtitle_font_size=opts['subtitle_font_size'] or 48)
    else:opts.update(video_width=100,video_height=76)
    # Use the same existing subtitle/title styling. No title auto-single-line change.
    ass=folder/(label+'_'+mode+'.ass')
    visible=cues if burn else []
    vw,vh,vx,vy=make_ass(ass,visible,opts,stream,duration,width,height)
    # make_ass places empty caption tracks over video; keep the normal source fit.
    base=f'color=c=black:s={width}x{height}:r=30:d={duration}[bg]'
    inputs=['-i',source]
    if p['background']:
        inputs+=['-loop','1','-i',valid_file(p['background'],'背景图')]
        base=f'[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=30[bg]'
    vf=base+f';[0:v]scale={vw}:{vh}:flags=lanczos,setsar=1,fps=30[src];[bg][src]overlay={vx}:{vy}:shortest=1'
    if burn or opts.get('title'):vf+=f",ass=filename='{ass.name}':fontsdir=fonts"
    vf+='[v]'
    fonts=Path(__file__).parent/'fonts'
    if fonts.exists() and not (folder/'fonts').exists():shutil.copytree(fonts,folder/'fonts')
    out=folder/(label+'_'+mode+'.mp4')
    has_audio=any(s['codec_type']=='audio' for s in probe(source,cancel)['streams'])
    if not has_audio:inputs+=['-f','lavfi','-i',f'anullsrc=r=48000:cl=stereo:d={duration}']
    audio_index=0 if has_audio else (2 if p['background'] else 1)
    ff([*inputs,'-filter_complex_threads','1','-filter_complex',vf,'-map','[v]','-map',f'{audio_index}:a:0','-af','aresample=48000,aformat=channel_layouts=stereo','-c:v','libx264','-preset','fast','-crf','18','-c:a','aac','-b:a','192k','-t',duration,out],cancel,cwd=folder)
    return out

def cover_clip(image,mode,p,folder,cancel):
    width,height=(1920,1080) if mode=='landscape' else (1080,1920)
    with Image.open(image) as im:ratio=im.width/im.height
    target=width/height
    if abs(ratio-target)>.04 and p['cover_fit']=='ask':raise ValueError('封面比例与输出不符。请选择对应封面，或明确选择等比例留边/裁切；不会拉伸。')
    fit='increase' if p['cover_fit']=='crop' else 'decrease'
    vf=f'scale={width}:{height}:force_original_aspect_ratio={fit},'+(f'crop={width}:{height}' if fit=='increase' else f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black')+',setsar=1,fps=30'
    out=folder/('cover_'+mode+'.mp4')
    ff(['-loop','1','-i',image,'-f','lavfi','-i',f'anullsrc=r=48000:cl=stereo:d={p["cover_seconds"]}','-vf',vf,'-t',p['cover_seconds'],'-c:v','libx264','-preset','fast','-crf','18','-c:a','aac','-b:a','192k',out],cancel)
    return out

def concat_clips(clips,out,folder,cancel):
    # Inputs are freshly encoded homogeneous local paths; no user text enters concat syntax.
    listing=folder/('concat_'+uuid.uuid4().hex+'.txt')
    listing.write_text(''.join("file '"+str(Path(p).resolve()).replace("'","'\\''")+"'\n" for p in clips),encoding='utf8')
    ff(['-f','concat','-safe','0','-i',listing,'-map','0:v:0','-map','0:a:0','-c','copy','-movflags','+faststart',out],cancel)

def process(job,cancel,progress=lambda s:None,preview=False):
    p=normalize(job.get('sequence'));output=Path(job['output']).resolve();output.mkdir(parents=True,exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='YangNing_Next_',dir=output))
    cache_root=output/'.yangning_cache';cache_root.mkdir(exist_ok=True)
    atomic_json(folder/'project.json',{'schema':1,'job':job})
    main_job=dict(job)
    if p['combined']:main_job,p=split_combined(main_job,p,folder,cancel,progress)
    intro,intro_cues=opening(main_job,p,folder,cancel,progress) if p['intro_enabled'] else (None,[])
    main=aligned(main_job,cache_root,cancel,progress)
    body=main/'video.mp4';body_cues=parse_srt(main/'subtitles.srt')
    ending=valid_file(p['outro_video'],'片尾视频') if p['outro_enabled'] else None
    stream=next(s for s in probe(body,cancel)['streams'] if s['codec_type']=='video')
    duration=seconds(body,cancel)+(seconds(intro,cancel) if intro else 0)+(seconds(ending,cancel) if ending else 0)
    results=[]
    recommendation_duration=duration+(p['cover_seconds'] if any(p.get(k) for k in ('cover','cover_landscape','cover_portrait')) else 0)
    for mode in choose_modes(p,recommendation_duration,stream):
        progress(('预览' if preview else '导出')+'：'+('横版16:9' if mode=='landscape' else '竖版9:16'))
        parts=[];cues=[];offset=0
        mode_body=body
        layout=p['layouts'][mode]
        if layout['remove_chinese'] and layout.get('clean_video'):
            clean=valid_file(layout['clean_video'],'无字幕原片')
            if abs(seconds(clean,cancel)-seconds(main_job['video'],cancel))>.1:raise ValueError('无字幕原片时长与正文原片不同。')
            clean_job={**main_job,'video':clean}
            mode_body=aligned(clean_job,cache_root,cancel,progress)/'video.mp4'
        elif layout['remove_chinese']:
            if layout.get('repair_approved')==repair_key(main_job['video'],layout.get('repair_roi',''),layout.get('repair_temporal',True)):
                layout['repair_approved']=repair_key(body,layout['repair_roi'],layout.get('repair_temporal',True))
        cover=p['cover_'+mode] if p['output_mode']=='both' else p['cover'] or p['cover_'+mode]
        if cover:
            parts.append(cover_clip(valid_file(cover,'封面图'),mode,p,folder,cancel));offset=p['cover_seconds']
        for label,source,subs,style in [('opening',intro,intro_cues,{}),('body',str(mode_body),body_cues,job.get('publish_settings') or {}),('ending',ending,[],{})]:
            if not source:continue
            part=compose_segment(source,subs,style,mode,p,folder,cancel,job.get('burn',False),label,repair_chinese=label=='body' and not layout.get('clean_video'))
            parts.append(part)
            base=len(cues);cues.extend((base+i+1,a+offset,b+offset,t) for i,(_,a,b,t) in enumerate(subs));offset+=seconds(part,cancel)
        full=folder/('assembled_'+mode+'.mp4')
        if cover and p['cover_transition']=='dissolve':
            # Fade between two actual images. Hold only the next segment's first
            # frame as a transition handle; its speech/content still starts at D.
            first=parts[1];transition=folder/('cover_transition_'+mode+'.mp4')
            ff(['-i',parts[0],'-i',first,'-filter_complex_threads','1','-filter_complex',f'[1:v]tpad=start_duration=0.5:start_mode=clone[n];[0:v][n]xfade=transition=fade:duration=0.5:offset={p["cover_seconds"]-.5}[v];[0:a][1:a]concat=n=2:v=0:a=1[a]','-map','[v]','-map','[a]','-c:v','libx264','-preset','fast','-crf','18','-c:a','aac','-b:a','192k',transition],cancel)
            parts=[transition,*parts[2:]]
        concat_clips(parts,full,folder,cancel)
        actual=seconds(full,cancel)
        if abs(actual-offset)>.3:raise RuntimeError('拼接时长检查失败，未标记完成。')
        streams=probe(full,cancel)['streams'];video_stream=next(v for v in streams if v['codec_type']=='video');audio_stream=next(v for v in streams if v['codec_type']=='audio')
        if abs(float(video_stream['duration'])-float(audio_stream['duration']))>.18:raise RuntimeError('完整项目音视频结尾偏差超过限制，未标记完成。')
        if cues and cues[-1][2]>actual+.05:raise RuntimeError('最后一句字幕超出完整视频。')
        write_srt(folder/('complete_'+mode+'.srt'),cues)
        decode=ff(['-xerror','-i',full,'-f','null','-'],cancel)
        if decode.strip():raise RuntimeError('完整解码有异常。')
        if preview:
            start=p['preview_start'];length=min(p['preview_seconds'],actual-start)
            if length<=0:raise ValueError('预览开始位置超出完整视频。')
            dest=folder/('preview_'+mode+'.mp4')
            ff(['-i',full,'-ss',start,'-t',length,'-c:v','libx264','-preset','fast','-crf','18','-c:a','aac',dest],cancel)
        else:
            dest=unique_output(output,job.get('name') or Path(job['video']).stem,job.get('language','ja'),mode)
            try:os.replace(full,dest)
            except Exception:dest.unlink(missing_ok=True);raise
            shutil.copyfile(folder/('complete_'+mode+'.srt'),dest.with_suffix('.srt'))
        results.append({'mode':mode,'path':str(dest),'duration':actual,'full_decode_passed':True})
    # Keep UI-compatible folder entry points without flattening editable originals.
    shutil.copyfile(results[0]['path'],folder/'video.mp4')
    atomic_json(folder/'report.json',{'status':'completed','results':results,'preview':preview,'listening_review':'not_performed','limitations':['低资源字幕区域修复不等于AI背景重建，需预览确认。','人声分离效果需用户试听确认；未默认启用未通过的模型。']})
    return str(folder)
