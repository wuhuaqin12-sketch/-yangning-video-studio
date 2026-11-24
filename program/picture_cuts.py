"""Conservative picture cuts in verified original-audio silence between cues."""
import re

import numpy as np
from media import executable,run


def quiet_picture_cuts(video,source,duration,has_audio,cancel,needed=None):
    """Prefer silent gaps, then small visually smooth cuts within one sentence."""
    silences=[]
    if has_audio:
        log=run([executable('ffmpeg'),'-hide_banner','-i',str(video),'-vn',
                 '-af','silencedetect=noise=-25dB:d=0.12','-f','null','-'],cancel)
        silences=[tuple(map(float,row)) for row in re.findall(
            r'silence_start: ([\d.]+).*?silence_end: ([\d.]+)',log,re.S)]
    import cv2
    cap=cv2.VideoCapture(str(video))
    if not cap.isOpened():return []
    def frame(t):
        cap.set(cv2.CAP_PROP_POS_MSEC,t*1000)
        ok,im=cap.read()
        return cv2.resize(cv2.cvtColor(im,cv2.COLOR_BGR2GRAY),(160,90)) if ok else None
    cuts=[]
    try:
        for index,(_,start,end,_) in enumerate(source):
            next_start=source[index+1][1] if index+1<len(source) else duration
            deficit=(needed or {}).get(source[index][0],float('inf'))
            if deficit<=.05:continue
            # Keep at least 0.25 seconds of each gap and margins at both cues.
            candidates=[]
            for a,b in silences:
                a=max(a,end+.10);b=min(b,next_start-.10)
                if b-a<.38:continue
                cut_end=min(b-.12,a+min(.8,deficit))
                if cut_end-a<.15:continue
                before,after=frame(a),frame(cut_end)
                if before is None or after is None:continue
                difference=float(np.mean(cv2.absdiff(before,after)))
                center=float(np.mean(cv2.absdiff(before[15:75,40:120],after[15:75,40:120])))
                if difference>5. or center>6.:continue
                candidates.append(dict(cue=source[index][0],start=round(a,4),
                                       end=round(cut_end,4),frame_difference=round(difference,2),
                                       reason='原声静音、位于原字幕句间且画面变化较小；仍需查看动作'))
            if candidates:
                chosen=max(candidates,key=lambda c:c['end']-c['start'])
                cuts.append(chosen);deficit-=chosen['end']-chosen['start']
            if deficit<=.35 or end-start<1.35:continue
            # Original audio is replaced by the dub. Intra-cue cuts are allowed
            # only when the start/end poses AND an intermediate frame are close.
            # Keep .35 seconds at each end and .25 seconds between cuts.
            frames={}
            for t in np.arange(start+.35,end-.35,.15):
                image=frame(float(t))
                if image is not None:frames[round(float(t),3)]=image
            ranked=[]
            times=list(frames)
            for a in times:
                for b in times:
                    length=b-a
                    if not .30<=length<=.65 or b>end-.35:continue
                    first,last=frames[a],frames[b]
                    middle=frames[min(times,key=lambda t:abs(t-(a+b)/2))]
                    full=float(np.mean(cv2.absdiff(first,last)))
                    center=float(np.mean(cv2.absdiff(first[15:75,40:120],last[15:75,40:120])))
                    middle_change=float(np.mean(cv2.absdiff(first[15:75,40:120],middle[15:75,40:120])))
                    changed=float(np.mean(cv2.absdiff(first[17:90,30:130],last[17:90,30:130])>20))
                    if full>4. or center>5.5 or middle_change>7. or changed>.04:continue
                    ranked.append((full+center+middle_change,a,b))
            selected=[]
            for _,a,b in sorted(ranked):
                if deficit<=.35 or len(selected)>=3:break
                if any(a<c['end']+.25 and b>c['start']-.25 for c in selected):continue
                if any(a<c['end']+.25 and b>c['start']-.25 for c in cuts if c['cue']==source[index][0]):continue
                selected.append(dict(cue=source[index][0],start=a,end=b,
                    reason='同一句中间的姿态与动作变化较小；请逐处预览是否有跳切'))
                deficit-=b-a
            cuts.extend(selected)
    finally:cap.release()
    return cuts


def picture_clock(source,cuts,duration):
    """Map the source to a virtual timeline with the approved gaps removed."""
    ordered=sorted(cuts,key=lambda c:c['start'])
    for i,c in enumerate(ordered):
        if not 0<=c['start']<c['end']<=duration or i and c['start']<ordered[i-1]['end']:
            raise ValueError('原画面空白剪切范围无效')
        cue=next((j for j,s in enumerate(source) if s[0]==c['cue']),None)
        if cue is None:raise ValueError('原画面剪切没有对应句子')
        s=source[cue];next_start=source[cue+1][1] if cue+1<len(source) else duration
        within=s[1]+.30<=c['start']<c['end']<=s[2]-.30
        gap=s[2]<=c['start']<c['end']<=next_start
        if not (within or gap):raise ValueError('不能跨句或剪切句首句尾画面')
    def virtual(t):
        return t-sum(max(0,min(t,c['end'])-c['start']) for c in ordered if t>c['start'])
    virtual_source=[(i,virtual(a),virtual(b),txt) for i,a,b,txt in source]
    vd=virtual(duration)
    def restore(t):
        u=t
        for c in ordered:
            a=virtual(c['start'])
            if u>=a-1e-9:t+=c['end']-c['start']
        return t
    return virtual_source,vd,restore,virtual
