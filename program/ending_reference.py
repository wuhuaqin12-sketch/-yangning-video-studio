"""Conservative local matching of a shared original ending, independent of language."""
import hashlib,json,math,tempfile,uuid
from pathlib import Path
import numpy as np
from desktop_update import atomic_json
from media import run,probe,executable,Cancelled
from ending_presets import digest

FPS=8
ALGORITHM='ending-template-rgb-edge-v1'

def stamp(path):
    p=Path(path).resolve();s=p.stat()
    return dict(path=str(p),size=s.st_size,modified=s.st_mtime_ns)

def duration(path,cancel):
    info=probe(path,cancel)
    if not any(s.get('codec_type')=='video' for s in info['streams']):raise ValueError('请选择含画面的片尾视频。')
    value=float(info['format']['duration'])
    if not math.isfinite(value) or value<=0:raise ValueError('无法读取视频时长。')
    return value

def metadata(root):
    index=Path(root)/'reference.json'
    if not index.is_file():return None
    data=json.loads(index.read_text(encoding='utf-8-sig'))
    if data.get('schema')!=1 or data.get('algorithm')!=ALGORITHM:raise ValueError('原片尾参考格式已变，请重新保存。')
    name=data.get('file','')
    if not name or Path(name).name!=name or '/' in name or '\\' in name:raise ValueError('原片尾参考路径无效。')
    return data

def load_reference(root):
    data=metadata(root)
    if data is None:raise ValueError('请先保存一次确认好的原片尾参考，不能用新增免责声明后的片尾代替。')
    path=Path(root)/data['file']
    if not path.is_file() or digest(path)!=data['sha256']:raise ValueError('原片尾参考丢失或发生变化，请重新保存。')
    return path,data

def samples(path,start,length,cancel):
    # Raw thumbnails remain under 5 MB for a five-minute search, with bounded batches.
    with tempfile.TemporaryDirectory(prefix='ending_samples_') as d:
        out=Path(d)/'frames.rgb'
        run([executable('ffmpeg'),'-nostdin','-v','error','-y','-ss',str(start),'-i',str(path),'-t',str(length),'-an','-vf',f'fps={FPS},scale=32:18:flags=area','-pix_fmt','rgb24','-f','rawvideo',str(out)],cancel)
        raw=np.fromfile(out,dtype=np.uint8)
    if not raw.size or raw.size%(32*18*3):raise ValueError('视频抽帧失败，请检查素材。')
    return raw.reshape(-1,18,32,3).astype(np.float32)/255

def _features(frames):
    gray=frames.mean(axis=3)
    edge=np.concatenate((np.diff(gray,axis=1).reshape(len(frames),-1),np.diff(gray,axis=2).reshape(len(frames),-1)),axis=1)
    return frames.reshape(len(frames),-1),edge,gray.std(axis=(1,2))

def save_reference(root,source,start,cancel,progress=lambda _:None):
    start=float(start);total=duration(source,cancel);length=total-start
    if not math.isfinite(start) or start<0 or not 2<=length<=120:raise ValueError('原片尾参考须为2–120秒；请确认原片尾开始位置。')
    before=stamp(source);root=Path(root);root.mkdir(parents=True,exist_ok=True)
    temp=root/('pending_'+uuid.uuid4().hex+'.mp4')
    try:
        progress('保存原片尾画面参考（本地、无音轨，不修改原视频）')
        run([executable('ffmpeg'),'-nostdin','-v','error','-y','-ss',str(start),'-i',str(source),'-t',str(length),'-an','-vf',f'fps={FPS},scale=320:180:flags=area','-c:v','libx264','-preset','fast','-crf','14','-pix_fmt','yuv420p',str(temp)],cancel)
        frames=samples(temp,0,length,cancel);_,_,texture=_features(frames)
        if int(np.sum(texture>.025))<min(5,len(frames)):raise ValueError('参考画面过于单一或接近纯黑，无法可靠定位；请选含原片尾标志或文字的完整片尾。')
        if stamp(source)!=before:raise ValueError('保存期间原视频发生变化，请重试。')
        fingerprint=digest(temp);name='reference_'+fingerprint+'.mp4';target=root/name
        temp.replace(target)
        data=dict(schema=1,algorithm=ALGORITHM,file=name,sha256=fingerprint,seconds=length)
        atomic_json(root/'reference.json',data)
        return data
    finally:temp.unlink(missing_ok=True)

def detect(root,source,cancel,progress=lambda _:None):
    reference,data=load_reference(root);before=stamp(source);total=duration(source,cancel)
    length=float(data['seconds'])
    if total<length-.125:raise ValueError('完整视频比原片尾参考还短，不能自动替换。')
    start=max(0,math.floor((total-min(total,min(300,max(60,length*3))))*FPS)/FPS)
    progress('在视频末尾匹配固定片尾画面，不使用字幕结束时间猜测')
    ref=samples(reference,0,length,cancel);target=samples(source,start,total-start,cancel)
    n=min(len(ref),round(length*FPS));ref=ref[:n]
    count=len(target)-n+1
    if count<=0:raise ValueError('视频末尾不足以容纳完整原片尾参考，请手动确认。')
    rgb,edge,texture=_features(ref);trgb,tedge,_=_features(target)
    anchors=np.unique(np.concatenate((np.linspace(0,n-1,min(24,n)).round().astype(int),np.arange(min(3,n)),np.arange(max(0,n-3),n))))
    weights=np.where(texture[anchors]>.025,1.,.35);weights/=weights.sum()
    scores=np.zeros(count);fractions=np.zeros(count)
    for offset in range(0,count,32):
        if cancel.is_set():raise Cancelled('已停止片尾定位')
        indices=np.arange(offset,min(offset+32,count))[:,None]+anchors[None,:]
        distance=.75*np.mean(np.abs(trgb[indices]-rgb[anchors]),axis=2)+.25*np.mean(np.abs(tedge[indices]-edge[anchors]),axis=2)
        similarity=np.exp(-12*distance)
        scores[offset:offset+len(indices)]=similarity@weights
        fractions[offset:offset+len(indices)]=np.mean(similarity>=.90,axis=1)
    best=int(np.argmax(scores));score=float(scores[best]);where=start+best/FPS
    if score<.93 or fractions[best]<.85:raise ValueError(f'未找到可靠的相同原片尾（最高相似度{score:.0%}）。请检查参考、画幅或手动确认，原视频未修改。')
    others=scores.copy();radius=max(FPS,round(length*.05*FPS));others[max(0,best-radius):best+radius+1]=-1
    runner=float(np.max(others)) if len(others) else -1
    if runner>=score-.035:raise ValueError('末尾存在重复或过于相似的画面，无法唯一确定片尾开始位置，请手动确认。')
    if total-(where+length)>3:raise ValueError('匹配画面后仍有较长内容，不能确认是原片尾，请手动检查。')
    if where<=0:raise ValueError('匹配点位于视频开头，不能作为整片的原片尾边界。')
    if stamp(source)!=before:raise ValueError('定位期间原视频发生变化，请重新定位。')
    return dict(source_stamp=before,reference_id=data['sha256'],start=where,reference_seconds=length,score=score,uncertainty=1/FPS,algorithm=ALGORITHM)

def check_candidate(root,source,candidate):
    if stamp(source)!=candidate['source_stamp']:raise ValueError('完整视频已更换或修改，请重新定位。')
    _,current=load_reference(root)
    if not current or current['sha256']!=candidate['reference_id']:raise ValueError('原片尾参考已更换，请重新定位。')

def preview(root,source,candidate,start,cancel):
    check_candidate(root,source,candidate);start=float(start);total=duration(source,cancel)
    if not math.isfinite(start) or not 0<start<total:raise ValueError('片尾开始位置须在完整视频内部。')
    out=Path(root)/('boundary_preview_'+uuid.uuid4().hex+'.mp4');begin=max(0,start-3)
    run([executable('ffmpeg'),'-nostdin','-v','error','-y','-ss',str(begin),'-i',str(source),'-t',str(min(total,start+4)-begin),'-map','0:v:0','-map','0:a:0?','-vf','scale=640:-2','-c:v','libx264','-preset','fast','-crf','20','-c:a','aac',str(out)],cancel)
    check_candidate(root,source,candidate)
    return dict(path=str(out),start=start,source_stamp=candidate['source_stamp'],reference_id=candidate['reference_id'])
