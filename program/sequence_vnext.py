"""Optional cover/opening/body/ending workflow over the existing alignment engine.

Speech generation is intentionally absent. Original inputs are read-only.
"""
import json,math,os,shutil,tempfile,uuid
from pathlib import Path
from PIL import Image,ImageOps
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
    from engine import prepare,render
    from workflow import normalize as normalize_job
    j=normalize_job({**job,'publish_settings':{},'burn':False})
    key=processing_key(j);cache=folder/'processing_cache'/key;cache.mkdir(parents=True,exist_ok=True)
    index=cache/'index.json'
    if index.is_file():
        record=json.loads(index.read_text(encoding='utf8'));candidate=Path(record['folder'])
        if (candidate/'video.mp4').is_file() and (candidate/'report.json').is_file():
            if record.get('video_sha256')==file_digest(candidate/'video.mp4') and record.get('srt_sha256')==file_digest(candidate/'subtitles.srt'):
                if record.get('plan_sha256')!=file_digest(candidate/'pause_plan.csv'):
                    progress('停顿表已修改；复用定位结果，重新匹配画面与音频')
                    render(candidate,cancel,progress)
                    atomic_json(index,{'folder':str(candidate),'key':key,'video_sha256':file_digest(candidate/'video.mp4'),'srt_sha256':file_digest(candidate/'subtitles.srt'),'plan_sha256':file_digest(candidate/'pause_plan.csv')})
                progress('复用已完成的配音处理与逐句音画匹配')
                return candidate
    j['output']=str(cache)
    result=Path(prepare(j,cancel,progress));render(result,cancel,progress)
    atomic_json(index,{'folder':str(result),'key':key,'video_sha256':file_digest(result/'video.mp4'),'srt_sha256':file_digest(result/'subtitles.srt'),'plan_sha256':file_digest(result/'pause_plan.csv')})
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

def imported_background(p,source,folder,cancel,progress):
    path=valid_file(p['background_audio'],'已经去人声的背景音频')
    meta=probe(path,cancel);track=next((x for x in meta['streams'] if x['codec_type']=='audio'),None)
    if not track:raise ValueError('所选背景音乐文件没有音轨。')
    audio_length=float(track.get('duration',meta['format']['duration']))
    length=seconds(source,cancel);offset=p['background_audio_offset'];available=audio_length-offset
    if available+.12<length:raise ValueError(f'背景音频可用{available:.2f}秒，片头需要{length:.2f}秒。请提供足够长的纯音乐；不会自动循环或变速。')
    progress(f'导入外部背景音乐，仅用于片头{length:.2f}秒；替换该段原声，不执行人声分离')
    out=folder/'imported_background.wav'
    ff(['-ss',offset,'-i',path,'-vn','-af',f'aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={length},atrim=duration={length}','-c:a','pcm_s16le',out],cancel)
    return str(out)

def opening(job,p,folder,cancel,progress):
    source=valid_file(p['intro_video'],'片头视频')
    if p['intro_mode']=='original':
        if p.get('background_audio'):raise ValueError('已导入背景音乐，请选择使用导入背景音乐或替换讲话模式；保留全部原声不会混用外部音乐。')
        return source,[]
    background=imported_background(p,source,folder,cancel,progress) if p.get('background_audio') else None
    if p['intro_mode']=='external_music':
        if not background:raise ValueError('请选择已经去人声的背景音乐文件。')
        out=folder/'intro_external_music.mp4'
        ff(['-i',source,'-i',background,'-map','0:v:0','-map','1:a:0','-c:v','copy','-af',f'volume={p["intro_music_gain"]}','-c:a','aac','-b:a','192k',out],cancel)
        return str(out),[]
    audio=valid_file(p['intro_audio'],'片头配音');srt=valid_file(p['intro_srt'],'片头SRT')
    if not background and not p['intro_clean_audio']:raise ValueError('请导入已去人声的片头背景音乐，或勾选片头视频本身已去人声；也可选择完整保留原声。此版本不自动分离片头。')
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
        segments.append((a,b,start));placed.append((ref[0],start+cue[1]-a,start+cue[2]-a,cue[3]));previous=end
    from opening_audio import mix
    mixed=mix(audio,background or source,segments,duration,p['intro_music_gain'],folder,cancel,progress)
    dest=folder/'intro_mixed.mp4'
    ff(['-i',source,'-f','f32le','-ar','48000','-ac','2','-i',mixed,'-map','0:v:0','-map','1:a:0','-c:v','copy','-af',f'alimiter=limit=0.89:level=0:latency=1,apad=whole_dur={duration},atrim=duration={duration}','-c:a','aac','-b:a','192k','-t',duration,dest],cancel)
    streams=probe(dest,cancel)['streams'];track=next(x for x in streams if x['codec_type']=='audio')
    if abs(float(track['duration'])-duration)>.08:raise RuntimeError('片头混音音轨未覆盖完整画面，已停止。')
    if abs(seconds(dest,cancel)-duration)>.15:raise RuntimeError('片头混音改变了时长。')
    write_srt(folder/'intro_aligned.srt',placed)
    return str(dest),placed

def choose_modes(p,total,source_stream):
    if p['output_mode']=='both':return ['landscape','portrait']
    if p['output_mode']!='auto':return [p['output_mode']]
    # Recommendation only. Manual output mode always overrides it.
    return ['portrait'] if total<=180 and source_stream['height']>=source_stream['width'] else ['landscape']

def repair_key(source,roi,temporal=False,method='glyph'):
    if method!='glyph':raise ValueError('整块区域修复已移除，请重新生成仅文字与描边预览。')
    from glyph_removal import ALGORITHM
    return file_digest(source)+':'+roi+':'+ALGORITHM

def layout_repair_key(source,layout):
    key=repair_key(source,layout.get('repair_roi',''),layout.get('repair_temporal',True),layout.get('repair_method','glyph'))
    return key+':full-width' if layout.get('repair_full_width',True) else key

def full_width_subtitle_roi(source,roi,cancel):
    try:_,y,_,h=map(int,roi.split(','))
    except Exception as e:raise ValueError('请先填写字幕行区域 x,y,宽,高；扩宽只改变横向，保留你选择的上下范围。') from e
    from engine import square_pixel_stream
    stream=square_pixel_stream(next(s for s in probe(source,cancel)['streams'] if s['codec_type']=='video'))
    rotation=int(stream.get('tags',{}).get('rotate',0))
    for side in stream.get('side_data_list',[]):
        if 'rotation' in side:rotation=int(side['rotation'])
    width,height=(stream['height'],stream['width']) if abs(rotation)%180==90 else (stream['width'],stream['height'])
    if y<0 or h<2 or y+h>height:raise ValueError('字幕行的上下范围超出原视频。')
    return f'0,{y},{width},{h}'

def repair(source,layout,folder,cancel,preview=False,start=0,length=15,progress=lambda _:None):
    if not layout['remove_chinese']:return source
    if layout.get('clean_video'):
        clean=valid_file(layout['clean_video'],'无字幕原片')
        if abs(seconds(clean,cancel)-seconds(source,cancel))>.1:raise ValueError('无字幕原片时长与当前段不一致，请先正确匹配。')
        return clean
    roi=layout.get('repair_roi','').strip()
    try:x,y,w,h=map(int,roi.split(','))
    except Exception:raise ValueError('清除原中文字幕需要先点击“鼠标框选字幕行”选择文字行；修复预览可选。')
    stream=next(s for s in probe(source,cancel)['streams'] if s['codec_type']=='video')
    from engine import square_pixel_stream
    stream=square_pixel_stream(stream)
    rotation=int(stream.get('tags',{}).get('rotate',0))
    for side in stream.get('side_data_list',[]):
        if 'rotation' in side:rotation=int(side['rotation'])
    if abs(rotation)%180==90:stream['width'],stream['height']=stream['height'],stream['width']
    if layout.get('repair_full_width',True):
        x=0;w=stream['width'];progress(f'字幕区默认横向全宽：0,{y},{w},{h}；上下范围不变。')
    if min(x,y)<0 or min(w,h)<2 or x+w>stream['width'] or y+h>stream['height']:raise ValueError('字幕处理区域须位于原视频内，不能裁掉老师画面。')
    method=layout.get('repair_method','glyph')
    if method!='glyph':raise ValueError('整块区域修复已移除，请重新生成仅文字与描边预览。')
    name=('repair_preview_' if preview else 'repaired_')+uuid.uuid4().hex[:8]+'.mp4';out=folder/name
    from glyph_removal import process
    duration=min(length,seconds(source,cancel)-start) if preview else seconds(source,cancel)
    if duration<=0:raise ValueError('预览起点超出视频时长。')
    return process(source,out,stream,(x,y,w,h),cancel,start if preview else 0,duration,progress)

def compose_segment(source,cues,style,mode,p,folder,cancel,burn,label,repair_chinese=False,progress=lambda _:None):
    from publish import make_ass
    from publish_style import normalize_style
    width,height=(1920,1080) if mode=='landscape' else (1080,1920)
    if repair_chinese:source=repair(source,p['layouts'][mode],folder,cancel)
    stream=next(s for s in probe(source,cancel)['streams'] if s['codec_type']=='video')
    from engine import square_pixel_stream
    stream=square_pixel_stream(stream)
    rotation=int(stream.get('tags',{}).get('rotate',0))
    for side in stream.get('side_data_list',[]):
        if 'rotation' in side:rotation=int(side['rotation'])
    if abs(rotation)%180==90:stream['width'],stream['height']=stream['height'],stream['width']
    duration=seconds(source,cancel)
    layout=p['layouts'][mode]
    chosen={**(style or {}),**layout.get('style',{})} if label=='body' else dict(style or {})
    for k in ('title_y','title_font_size','subtitle_font_size'):
        if layout.get(k) not in ('',None) and label=='body':chosen[k]=float(layout[k])
    opts=normalize_style(chosen)
    opts.update(subtitle_area='video' if mode=='landscape' else 'below_video',subtitle_offset_y=p['layouts'][mode]['subtitle_offset_y'])
    if mode=='landscape':
        opts.update(video_width=chosen.get('video_width',100),video_height=chosen.get('video_height',100),subtitle_font_size=opts['subtitle_font_size'] or 48)
    else:opts.update(video_width=chosen.get('video_width',100),video_height=chosen.get('video_height',76))
    if label=='ending':opts.update(title='',video_width=100,video_height=100,subtitle_area='video')
    # Use the same existing subtitle/title styling. No title auto-single-line change.
    ass=folder/(label+'_'+mode+'.ass')
    visible=cues if burn else []
    vw,vh,vx,vy=make_ass(ass,visible,opts,stream,duration,width,height,auto_background=label=='body' and layout.get('auto_long_subtitles',True))
    report=json.loads((folder/'layout_report.json').read_text(encoding='utf8'))
    atomic_json(folder/(label+'_'+mode+'.layout.json'),report)
    if report.get('auto_background'):progress('横版长字幕：完整画面已等比例缩入上方，字幕放在下方背景。')
    if report.get('split_cues'):progress('字幕已完整分屏，页时间按字数分配，不改变配音；需预览核对。')
    if report.get('short_pages'):progress('字幕排版提醒：编号'+','.join(map(str,report['short_pages']))+'部分页面不足1秒，请调整该句字幕时间或字号。')
    opening_title=False
    # make_ass places empty caption tracks over video; keep the normal source fit.
    base=f'color=c=black:s={width}x{height}:r=30:d={duration}[bg]'
    inputs=['-i',source]
    if p['background']:
        inputs+=['-loop','1','-i',valid_file(p['background'],'背景图')]
        base=f'[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=30[bg]'
    vf=base+f';[0:v]scale={vw}:{vh}:flags=lanczos,setsar=1,fps=30[src];[bg][src]overlay={vx}:{vy}:shortest=1'
    if burn or opts.get('title') or opening_title:vf+=f",ass=filename='{ass.name}':fontsdir=fonts"
    vf+='[v]'
    fonts=Path(__file__).parent/'fonts'
    if fonts.exists() and not (folder/'fonts').exists():shutil.copytree(fonts,folder/'fonts')
    out=folder/(label+'_'+mode+'.mp4')
    has_audio=any(s['codec_type']=='audio' for s in probe(source,cancel)['streams'])
    if not has_audio:inputs+=['-f','lavfi','-i',f'anullsrc=r=48000:cl=stereo:d={duration}']
    audio_index=0 if has_audio else (2 if p['background'] else 1)
    ff([*inputs,'-filter_complex_threads','1','-filter_complex',vf,'-map','[v]','-map',f'{audio_index}:a:0','-af',f'aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={duration},atrim=duration={duration}','-c:v','libx264','-preset','fast','-crf','18','-c:a','aac','-b:a','192k','-t',duration,out],cancel,cwd=folder)
    return out

def cover_clip(image,mode,p,folder,cancel):
    width,height=(1920,1080) if mode=='landscape' else (1080,1920)
    normalized=folder/('cover_image_'+mode+'.png')
    with Image.open(image) as im:
        im=ImageOps.exif_transpose(im).convert('RGB');ratio=im.width/im.height;im.save(normalized)
    target=width/height
    if abs(ratio-target)>.04 and p['cover_fit']=='ask':raise ValueError('封面比例与输出不符。请选择对应封面，或明确选择等比例留边/裁切；不会拉伸。')
    fit='increase' if p['cover_fit']=='crop' else 'decrease'
    vf=f'scale={width}:{height}:force_original_aspect_ratio={fit},'+(f'crop={width}:{height}' if fit=='increase' else f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black')+',setsar=1,fps=30'
    out=folder/('cover_'+mode+'.mp4')
    ff(['-loop','1','-i',normalized,'-f','lavfi','-i',f'anullsrc=r=48000:cl=stereo:d={p["cover_seconds"]}','-vf',vf,'-t',p['cover_seconds'],'-c:v','libx264','-preset','fast','-crf','18','-c:a','aac','-b:a','192k',out],cancel)
    return out

def concat_clips(clips,out,folder,cancel):
    durations=[]
    for clip in clips:
        streams=probe(clip,cancel)['streams'];v=next(x for x in streams if x['codec_type']=='video');a=next(x for x in streams if x['codec_type']=='audio')
        durations.append(float(v['duration']))
        if abs(float(v['duration'])-float(a['duration']))>.08:raise RuntimeError('拼接片段的音轨未覆盖全部画面，已停止，避免下一段无声。')
    # Inputs are freshly encoded homogeneous local paths; no user text enters concat syntax.
    listing=folder/('concat_'+uuid.uuid4().hex+'.txt')
    listing.write_text(''.join("file '"+str(Path(p).resolve()).replace("'","'\\''")+"'\nduration "+format(length,'.9f')+"\n" for p,length in zip(clips,durations)),encoding='utf8')
    ff(['-f','concat','-safe','0','-i',listing,'-map','0:v:0','-map','0:a:0','-c:v','copy','-af','aresample=48000:async=1:first_pts=0','-c:a','aac','-b:a','192k','-movflags','+faststart',out],cancel)

def preflight_repair(job,p,cancel):
    source=valid_file(job['video'],'原视频')
    from roi_picker import normalized_stream
    stream=normalized_stream(source,cancel);duration=seconds(source,cancel);estimate=duration
    if job.get('audio') and Path(job['audio']).is_file():estimate=max(estimate,seconds(job['audio'],cancel))
    if p.get('intro_enabled'):estimate+=seconds(valid_file(p['intro_video'],'片头视频'),cancel)
    if p.get('outro_enabled'):estimate+=seconds(valid_file(p['outro_video'],'片尾视频'),cancel)
    if any(p.get(k) for k in ('cover','cover_landscape','cover_portrait')):estimate+=p['cover_seconds']
    for mode in choose_modes(p,estimate,stream):
        layout=p['layouts'][mode]
        if not layout['remove_chinese']:continue
        if layout.get('clean_video'):
            clean=valid_file(layout['clean_video'],'无字幕原片')
            if abs(seconds(clean,cancel)-duration)>.1:raise ValueError('无字幕原片时长与原视频不同，请先正确匹配。')
            continue
        try:x,y,w,h=map(int,layout['repair_roi'].split(','))
        except Exception:raise ValueError(('横版' if mode=='landscape' else '竖版')+'去字幕尚未设置区域。请先点击“鼠标框选字幕行”，15秒预览可选；尚未开始处理音频。')
        if layout['repair_full_width']:x=0;w=stream['width']
        if min(x,y)<0 or min(w,h)<2 or x+w>stream['width'] or y+h>stream['height']:raise ValueError('字幕区域超出原视频，请重新鼠标框选。')

def process(job,cancel,progress=lambda s:None,preview=False):
    if (job.get('sequence') or {}).get('combined'):raise ValueError('完整视频切分与片尾替换已撤下，请分别导入片头、正文和片尾视频。')
    p=normalize(job.get('sequence'))
    p.update(opening_title_enabled=False,opening_topic_enabled=False,disclaimer_enabled=False,combined_replace_outro=False)
    if p.get('background_audio') and not p['intro_enabled']:
        raise ValueError('片头背景音乐只能用于独立片头，请先勾选添加片头并选择片头视频。')
    preflight_repair(job,p,cancel)
    output=Path(job['output']).resolve();output.mkdir(parents=True,exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='YangNing_Next_',dir=output))
    cache_root=output/'.yangning_cache';cache_root.mkdir(exist_ok=True)
    atomic_json(folder/'project.json',{'schema':1,'job':job})
    main_job=dict(job)
    p['_language']=main_job.get('language','ja')
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
            if layout.get('repair_approved')==layout_repair_key(main_job['video'],layout):
                layout['repair_approved']=layout_repair_key(body,layout)
        cover=p['cover_'+mode] if p['output_mode']=='both' else p['cover'] or p['cover_'+mode]
        if cover:
            parts.append(cover_clip(valid_file(cover,'封面图'),mode,p,folder,cancel));offset=p['cover_seconds']
        for label,source,subs,style in [('opening',intro,intro_cues,{}),('body',str(mode_body),body_cues,job.get('publish_settings') or {}),('ending',ending,[],{})]:
            if not source:continue
            part=compose_segment(source,subs,style,mode,p,folder,cancel,job.get('burn',False),label,repair_chinese=label=='body' and not layout.get('clean_video'),progress=progress)
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
        packet_data=json.loads(run([executable('ffprobe'),'-v','error','-select_streams','a:0','-show_packets','-show_entries','packet=pts_time,duration_time','-of','json',str(full)],cancel))['packets']
        previous=None
        for packet in packet_data:
            timestamp=float(packet.get('pts_time',0));span=float(packet.get('duration_time',0))
            if span>.08 or (previous is not None and timestamp-previous>.08):raise RuntimeError('音频时间戳存在异常缺口，已停止交付。')
            previous=timestamp
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
    atomic_json(folder/'report.json',{'status':'completed','body_analysis':str(main),'results':results,'preview':preview,'listening_review':'not_performed','limitations':['低资源字幕区域修复不等于AI背景重建，需预览确认。','人声分离效果需用户试听确认；未默认启用未通过的模型。']})
    return str(folder)
