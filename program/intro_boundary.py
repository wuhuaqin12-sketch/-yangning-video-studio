"""Intro split proposals from numbered source cues and validated narration timing."""
import hashlib,json,tempfile,math
from pathlib import Path
import numpy as np
from media import probe,parse_srt,run,executable,stamp,Cancelled
from project_vnext import file_digest
from ending_reference import stamp as file_stamp

def write_srt(path,cues):
    Path(path).write_text('\n\n'.join(f'{i}\n{stamp(a)} --> {stamp(b)}\n{text}' for i,a,b,text in cues)+'\n',encoding='utf-8-sig')

def alignment_token(video,audio,source_srt,aligned_srt):
    return hashlib.sha256(json.dumps([file_digest(p) for p in (video,audio or video,source_srt,aligned_srt)]).encode()).hexdigest()

def cue_boundary(cues,last_id,total):
    ids=[c[0] for c in cues]
    if last_id not in ids or ids.index(last_id)==len(ids)-1:raise ValueError('找不到片头最后一条及其后的正文字幕，请检查片头最后编号。')
    n=ids.index(last_id);last=cues[n];first=cues[n+1]
    if not 0<first[1]<total or last[2]>first[1]+.001:raise ValueError('SRT片头与正文分界越界或重叠，请提供对应原视频/配音的正确SRT。')
    return n,first[1],last[2],first[0]

def audio_only_boundary(audio,source_srt,last_id,aligned_srt,folder,cancel):
    """Use the narration clock independently of the source video's duration."""
    audio=Path(audio);source_srt=Path(source_srt);aligned_srt=Path(aligned_srt)
    if any(not p.is_file() for p in (audio,source_srt,aligned_srt)):
        raise ValueError('请导入整段配音、完整视频 SRT 和已对齐配音 SRT。')
    refs=parse_srt(source_srt);targets=parse_srt(aligned_srt)
    if [c[0] for c in refs]!=[c[0] for c in targets]:
        raise ValueError('视频与配音 SRT 编号不一致，请先校对。')
    total=float(probe(audio,cancel)['format']['duration'])
    _,next_start,last_end,body_id=cue_boundary(targets,int(last_id),total)
    if targets[-1][2]>total+.03:raise ValueError('配音 SRT 超出配音时长。')
    gap=next_start-last_end
    if gap<.04:raise ValueError('片头与正文配音之间没有可确认的停顿，请校对配音 SRT。')
    split=next_start-min(.12,gap/2)
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    begin=max(0,split-.8);raw=folder/'audio_boundary_check.f32'
    run([executable('ffmpeg'),'-nostdin','-v','error','-y','-ss',str(begin),'-i',str(audio),'-t',str(min(1.6,total-begin)),'-vn','-ar','8000','-ac','1','-f','f32le',str(raw)],cancel)
    signal=np.fromfile(raw,np.float32);center=round((split-begin)*8000)
    rms=lambda a:float(np.sqrt(np.mean(a*a))) if len(a) else 0
    chunks=[rms(signal[i:i+400]) for i in range(0,len(signal),400)]
    if rms(signal[max(0,center-120):center+120])>max(.0015,max(chunks or [0])*.18):
        raise ValueError('配音分界附近仍有明显声音，请核对已对齐 SRT 或手动确认安全停顿。')
    return dict(audio=split,body_id=body_id,last_id=int(last_id),aligned_srt=str(aligned_srt))

def video_only_boundary(video,source_srt,last_id,cancel):
    """Locate the original video boundary without requiring narration alignment."""
    video=Path(video);source_srt=Path(source_srt)
    if not video.is_file() or not source_srt.is_file():
        raise ValueError('请先导入完整原视频及对应原视频时间轴 SRT。')
    refs=parse_srt(source_srt)
    total=float(probe(video,cancel)['format']['duration'])
    _,head,_,body_id=cue_boundary(refs,int(last_id),total)
    if refs[-1][2]>total+.1:
        raise ValueError('原视频 SRT 超出视频时长，请检查时间轴。')
    return dict(video=head,body_id=body_id,last_id=int(last_id))

def detect(video,audio,source_srt,language,last_id,aligned_srt,folder,cancel,progress=lambda _:None):
    video=Path(video);audio=Path(audio) if audio else video;source_srt=Path(source_srt)
    for p in (video,audio,source_srt):
        if not p.is_file():raise ValueError('请先导入完整原视频、对应SRT及准备好的合并配音。')
    stamps={k:file_stamp(v) for k,v in dict(video=video,audio=audio,srt=source_srt).items()}
    refs=parse_srt(source_srt);total=float(probe(video,cancel)['format']['duration'])
    n,head,last_end,body_id=cue_boundary(refs,int(last_id),total)
    if refs[-1][2]>total+.1:raise ValueError('原视频SRT超出视频时长，请使用原视频对应时间轴。')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);same_audio=audio.resolve()==video.resolve()
    progress(f'按第{last_id}条结束、第{body_id}条正文开始提议片头分界；需预览确认')
    if same_audio:
        targets=refs;split=head;method='original_video_audio';warning='保留原视频原声，音频分界与视频一致。'
    else:
        audio_total=float(probe(audio,cancel)['format']['duration'])
        if aligned_srt:
            targets=parse_srt(aligned_srt);method='provided_aligned_srt'
        else:
            from multilingual import align,LANGUAGES
            if language not in LANGUAGES:raise ValueError('当前语言暂不能自动定位配音；请导入已对齐配音的SRT，不能用原视频时间猜配音分界。')
            progress('调用现有本地语音定位；首次可能准备组件/模型，可停止，不上传配音')
            targets=align(refs,str(audio),folder,cancel,progress,language,audio_total);method='local_reference_alignment'
        if [c[0] for c in refs]!=[c[0] for c in targets]:raise ValueError('原视频SRT与已对齐配音SRT的字幕编号必须一一对应。')
        _,next_start,audio_last_end,_=cue_boundary(targets,int(last_id),audio_total)
        if targets[-1][2]>audio_total+.03:raise ValueError('配音SRT超出配音音频时长。')
        gap=next_start-audio_last_end
        if gap<.04:raise ValueError('片头与正文配音之间没有可确认的停顿，不能安全自动切分。请试听或提供独立片头/正文配音。')
        # Keep up to 120ms before the first body word, rather than cutting its onset.
        split=next_start-min(.12,gap/2);warning='正文首词前保留少量缓冲；仍需试听确认。'
        begin=max(0,split-.8);length=min(1.6,audio_total-begin);raw=folder/'gap_check.f32'
        run([executable('ffmpeg'),'-nostdin','-v','error','-y','-ss',str(begin),'-i',str(audio),'-t',str(length),'-vn','-ar','8000','-ac','1','-f','f32le',str(raw)],cancel)
        signal=np.fromfile(raw,np.float32);center=round((split-begin)*8000);half=120
        local=signal[max(0,center-half):center+half];rms=lambda a:float(np.sqrt(np.mean(a*a))) if len(a) else 0
        chunks=[rms(signal[i:i+400]) for i in range(0,len(signal),400)]
        if rms(local)>max(.0015,max(chunks or [0])*.18):raise ValueError('配音SRT分界附近仍有明显声音，不能确认是安全停顿。请核对已对齐SRT或重新自动定位。')
    target=folder/'full_narration_aligned.srt';write_srt(target,targets)
    if any(file_stamp(p)!=stamps[k] for k,p in dict(video=video,audio=audio,srt=source_srt).items()):raise ValueError('定位期间素材发生变化，请重新定位。')
    token=alignment_token(video,audio,source_srt,target)
    return dict(video=head,audio=split,body_id=body_id,last_id=int(last_id),stamps=stamps,aligned_srt=str(target),token=token,method=method,warning=warning)

def verify(candidate,video,audio,source_srt):
    audio=audio or video
    if any(file_stamp(v)!=candidate['stamps'][k] for k,v in dict(video=video,audio=audio,srt=source_srt).items()):raise ValueError('原视频、配音或SRT已更换，请重新定位。')
    if alignment_token(video,audio,source_srt,candidate['aligned_srt'])!=candidate['token']:raise ValueError('自动定位结果已改变，请重新定位。')

def preview(candidate,video,audio,source_srt,kind,folder,cancel):
    verify(candidate,video,audio,source_srt);folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    at=candidate[kind];source=video if kind=='video' else (audio or video);begin=max(0,at-3)
    out=folder/('intro_boundary_'+kind+('.mp4' if kind=='video' else '.wav'))
    args=[executable('ffmpeg'),'-nostdin','-v','error','-y','-ss',str(begin),'-i',str(source),'-t','6']
    args+=['-map','0:v:0','-map','0:a:0?','-vf','scale=640:-2','-c:v','libx264','-preset','fast','-c:a','aac'] if kind=='video' else ['-vn','-c:a','pcm_s16le']
    run([*args,str(out)],cancel);verify(candidate,video,audio,source_srt)
    return dict(path=str(out),kind=kind,token=candidate['token'])
