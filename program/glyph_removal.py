"""Streaming, local white-caption removal. No scene/object-specific coordinates."""
import json,math,os,subprocess,tempfile,time,uuid
from pathlib import Path
import numpy as np
from media import executable,run,Cancelled

ALGORITHM='white-outline-v1'

def text_mask(frame,roi):
    try:import cv2
    except ImportError as e:raise RuntimeError('仅文字与描边处理缺少OpenCV，请重新运行测试版安装器；不会自动改用整块修复。') from e
    x,y,w,h=roi
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    # Current validated scope: near-white lettering with a dark outline.
    white=(np.min(frame,axis=2)>180)&((np.max(frame,axis=2).astype(int)-np.min(frame,axis=2))<70)
    outline=cv2.erode(gray,np.ones((5,5),np.uint8))<175
    bounds=np.zeros(gray.shape,np.uint8);bounds[y:y+h,x:x+w]=255
    mask=cv2.bitwise_and((white&outline).astype(np.uint8)*255,bounds)
    mask=cv2.bitwise_and(cv2.dilate(mask,np.ones((9,9),np.uint8)),bounds)
    # Preserve dark details immediately ABOVE any selected caption row.
    # Generic boundary protection; never hard-code a belt/person/video preset.
    protected=np.zeros_like(gray)
    a=max(0,y-38);b=max(a,y-3)
    protected[a:b,x:x+w]=(gray[a:b,x:x+w]<100).astype(np.uint8)*255
    protected=cv2.dilate(protected,np.ones((11,11),np.uint8))
    mask[protected>0]=0
    return mask

def remove_frame(frame,roi):
    import cv2
    mask=text_mask(frame,roi)
    fixed=cv2.inpaint(frame,mask,5,cv2.INPAINT_TELEA) if np.any(mask) else frame.copy()
    # Enforce the contract, including against unexpected library changes.
    fixed[mask==0]=frame[mask==0]
    return fixed,mask

def process(source,out,stream,roi,cancel,start=0,duration=None,progress=lambda _:None):
    """Use constant 30fps timestamps, matching the existing composition stage.

    Only a frame and its masks are held in RAM. Inputs stay read-only. Audio is
    taken from the same source time range and is never processed as speech.
    """
    try:import cv2
    except ImportError as e:raise RuntimeError('缺少OpenCV，请运行测试安装器补齐依赖；不会回退到整块修复。') from e
    cv2.setNumThreads(1)
    if cancel.is_set():raise Cancelled('已停止')
    width,height=int(stream['width']),int(stream['height'])
    size=width*height*3;out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    options=dict(creationflags=0x08000000 if os.name=='nt' else 0)
    ffmpeg=executable('ffmpeg');timing=['-ss',str(start)] if start else []
    limit=['-t',str(duration)] if duration is not None else []
    frames=changed=0;largest=0;decoder=encoder=None
    with tempfile.TemporaryDirectory(prefix='glyph_',dir=out.parent) as temp:
        silent=Path(temp)/'picture.mp4'
        with tempfile.TemporaryFile() as dlog,tempfile.TemporaryFile() as elog:
            try:
                decoder=subprocess.Popen([ffmpeg,'-nostdin','-v','error',*timing,'-i',str(source),*limit,'-an','-vf',f'scale={width}:{height},setsar=1,fps=30','-pix_fmt','bgr24','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE,stderr=dlog,**options)
                encoder=subprocess.Popen([ffmpeg,'-nostdin','-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{width}x{height}','-r','30','-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p',str(silent)],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=elog,**options)
                while True:
                    if cancel.is_set():raise Cancelled('已停止')
                    raw=decoder.stdout.read(size)
                    if not raw:break
                    if len(raw)!=size:raise RuntimeError('字幕处理视频解码帧不完整。')
                    frame=np.frombuffer(raw,np.uint8).reshape(height,width,3)
                    fixed,mask=remove_frame(frame,roi);count=int(np.count_nonzero(mask))
                    changed+=count;largest=max(largest,count);frames+=1
                    encoder.stdin.write(fixed.tobytes())
                    if frames%150==0:progress(f'仅文字与描边：已处理 {frames/30:.0f} 秒'+(f' / {duration:.0f} 秒' if duration else ''))
                encoder.stdin.close();decoder.stdout.close()
                for p,log in ((decoder,dlog),(encoder,elog)):
                    while p.poll() is None:
                        if cancel.is_set():raise Cancelled('已停止')
                        time.sleep(.05)
                    if p.returncode:
                        log.seek(0);raise RuntimeError(log.read().decode('utf8',errors='replace')[-4000:])
                if not frames:raise RuntimeError('预览范围没有可处理的视频帧。')
                if duration is not None and abs(frames/30-duration)>.1:raise RuntimeError('字幕处理时长与指定范围不一致，请检查素材。')
                run([ffmpeg,'-nostdin','-v','error','-y','-i',str(silent),*timing,'-i',str(source),'-map','0:v:0','-map','1:a:0?','-c:v','copy','-c:a','aac','-b:a','192k','-t',str(duration if duration is not None else frames/30),'-movflags','+faststart',str(out)],cancel)
            finally:
                for p in (decoder,encoder):
                    if p is not None and p.poll() is None:
                        p.terminate()
                        try:p.wait(timeout=5)
                        except subprocess.TimeoutExpired:p.kill();p.wait()
                    if p is not None:
                        for channel in (p.stdin,p.stdout):
                            if channel is not None:
                                try:channel.close()
                                except (OSError,ValueError):pass
    record=dict(algorithm=ALGORITHM,roi=list(roi),frames=frames,fps=30,duration=frames/30,changed_mask_pixels=changed,max_mask_pixels=largest,processing_scope='detected white text and dark outlines inside selected row',whole_rectangle_repair=False,limitations=['白字深描边启发式遮罩，不是OCR或AI重建；复杂画面可能误判、残留、模糊或闪烁。','素材需重新框选字幕行并预览确认。'])
    out.with_suffix('.glyph.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    progress('仅文字与描边处理完成。'+('未检测到匹配的白字描边，请检查区域或字体颜色。' if not changed else '请检查预览中的文字残留与画面细节。'))
    return str(out)
