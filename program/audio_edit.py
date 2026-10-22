import csv,json,re,wave,math
from pathlib import Path
import numpy as np
from media import run,executable,Cancelled

def detect(raw,rate,channels,cancel):
    log=run([executable('ffmpeg'),'-hide_banner','-f','f32le','-ar',str(rate),'-ac',str(channels),'-i',str(raw),'-af','silencedetect=noise=-42dB:d=0.10','-f','null','-'],cancel)
    # Pair in log order; a trailing silence may not have an end marker.
    duration=Path(raw).stat().st_size/(4*rate*channels)
    intervals=[];pending=None
    for kind,value in re.findall(r'silence_(start|end): ([\d.]+)',log):
        t=min(duration,max(0.,float(value)))
        if kind=='start':pending=t
        elif pending is not None:
            if t>pending:intervals.append((pending,t))
            pending=None
    if pending is not None and duration>pending:intervals.append((pending,duration))
    return intervals

def propose(cues,silences,duration,rate,channels,raw,trim=True,words=None,language=None):
    if not trim:return []
    events=[];pcm=np.memmap(raw,np.float32,'r').reshape(-1,channels)
    def very_quiet(a,b):
        # Broad Japanese token spans can contain real silence. Only override
        # such a span (or a cue without word timings) if EVERY 20ms window is
        # below -50 dBFS in EVERY channel. Never infer silence from timestamps.
        step=max(1,round(rate*.02));lo=max(0,round(a*rate));hi=min(len(pcm),round(b*rate))
        if hi<=lo:return False
        for i in range(lo,hi,step):
            block=np.asarray(pcm[i:min(i+step,hi)],dtype=np.float64)
            if not np.isfinite(block).all() or np.any(np.mean(block*block,axis=0)>1e-5):return False
        return True
    for a,b in silences:
        a=max(0.,a);b=min(duration,b)
        if b<=a:continue
        leading=a<.03;trailing=b>duration-.05
        if leading and trailing:continue  # No speech: do not turn it into a tiny clip.
        inside=any(s+.08<a and b<e-.08 for _,s,e,_ in cues)
        if leading:
            if b-a<.65:continue
            ca,cb=a,b-.25;reason='开头空白：保留0.25秒'
        elif trailing:
            if b-a<.85:continue
            ca,cb=a+.4,b;reason='结尾空白：保留0.4秒'
        else:
            keep=.55 if inside else .65;minimum=.95
            reason='句内长空白：保留0.55秒' if inside else '句间长空白：保留0.65秒'
            if language=='ja' and words:
                previous=[w for w in words if w['end']<=a+.06]
                following=[w for w in words if w['start']>=b-.06]
                left=previous[-1]['word'].strip() if previous else ''
                right=following[0]['word'].strip() if following else ''
                # Japanese aligner units are often characters, not words.
                # Shorten only real acoustic silence BETWEEN localized units.
                # Sokuon closures and silence inside units stay protected.
                if left and right:
                    if re.search(r'[。！？.!?][」』”"\s]*$',left):
                        minimum=.65;keep=.45;reason='句末停顿：保留0.45秒'
                    elif re.search(r'[、，,；;：:][」』”"\s]*$',left):
                        minimum=.45;keep=.28;reason='分句停顿：保留0.28秒'
                    elif not (left.endswith(('っ','ッ')) or right.startswith(('っ','ッ'))):
                        minimum=.30;keep=.18;reason='句内字词间空白：保留0.18秒'
            if b-a<minimum:continue
            ca,cb=a+keep/2,b-keep/2
        if language=='ja' and b-a<.95 and not very_quiet(ca,cb):continue
        conflicts=[w for w in (words or []) if w['start']-.025<cb and w['end']+.025>ca]
        # Keep genuine localized words protected. A unit enclosing the whole
        # silence is too coarse to veto acoustic evidence on its own.
        if conflicts:
            coarse=all(w['start']<=a+.03 and w['end']>=b-.03 and w['end']-w['start']>=1.2 for w in conflicts)
            if not coarse or not very_quiet(ca,cb):continue
            reason+='（粗粒度字词定位，已用音量复核）'
        elif inside and not words and not very_quiet(ca,cb):continue
        if cb-ca<.10:continue
        events.append(dict(enabled=True,kind='cut',start=ca,end=cb,seconds=cb-ca,reason=reason,safe_start=a,safe_end=b))
    # Compression mode does not insert extra pauses into already short gaps.
    return sorted(events,key=lambda e:e['start'])

def pause_summary(original,total,events,speed=1.0):
    cuts=[e for e in events if e['kind']=='cut']
    removed=sum(e['end']-e['start'] for e in cuts)
    def clock(t):
        mins,sec=divmod(t,60)
        return f'{int(mins)}分{sec:04.1f}秒'
    text=f'停顿压缩：{clock(original)} → {clock(total*speed)}；剪短{len(cuts)}处，共删除{removed:.2f}秒'
    if speed!=1.0:text+=f'；再以{speed:g}倍速输出：{clock(total)}（保持音调）'
    return text

def validate_events(events,duration):
    active=[];last=0
    for r in sorted(events,key=lambda e:float(e['start'])):
        if not r.get('enabled',True):continue
        r=dict(r);a=float(r['start']);b=float(r['end']);n=float(r['seconds']);lo=float(r['safe_start']);hi=float(r['safe_end'])
        if r['kind'] not in ('cut','add') or not all(math.isfinite(x) for x in (a,b,n,lo,hi)):raise ValueError('停顿计划含无效数值')
        if not 0<=lo<=a<=b<=hi<=duration+.002 or a<last-.0001:raise ValueError('停顿调整越界或重叠')
        if r['kind']=='cut':
            if b<=a:raise ValueError('删除区间必须有长度')
            r['seconds']=b-a;last=b
        else:
            if a!=b or not 0<=n<=1.2:raise ValueError('增加停顿须为0–1.2秒，且不能切断词语')
            last=a
        active.append(r)
    return active

def mapped(t,events):
    return t-sum(max(0,min(t,e['end'])-e['start']) for e in events if e['kind']=='cut' and t>e['start'])+sum(e['seconds'] for e in events if e['kind']=='add' and e['start']<t)

def apply(raw,dest,rate,channels,events,cancel):
    pcm=np.memmap(raw,np.float32,'r').reshape(-1,channels);duration=len(pcm)/rate;events=validate_events(events,duration);pos=0;written=0
    with Path(dest).open('wb') as out:
        def part(start,end,fadein,fadeout):
            nonlocal written
            cursor=start;nfade=round(rate*.003)
            while cursor<end:
                if cancel.is_set():raise Cancelled()
                z=min(end,cursor+rate*4);chunk=np.array(pcm[cursor:z],copy=True)
                if fadein and cursor==start:
                    n=min(nfade,len(chunk));chunk[:n]*=np.linspace(0,1,n)[:,None]
                if fadeout and z==end:
                    n=min(nfade,len(chunk));chunk[-n:]*=np.linspace(1,0,n)[:,None]
                out.write(chunk.astype('<f4',copy=False).tobytes());written+=len(chunk);cursor=z
        for ev in events:
            a=round(ev['start']*rate);part(pos,a,pos>0,True)
            if ev['kind']=='cut':pos=min(len(pcm),round(ev['end']*rate))
            else:
                n=round(ev['seconds']*rate);out.write(bytes(n*channels*4));written+=n;pos=a
        part(pos,len(pcm),pos>0,False)
    return written/rate

def export_plan(events,path):
    fields=['enabled','kind','start','end','seconds','reason','safe_start','safe_end']
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=fields);wr.writeheader();wr.writerows(events)
def import_plan(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    for r in rows:
        r['enabled']=str(r['enabled']).lower() in ('true','1','yes','是')
        for k in ('start','end','seconds','safe_start','safe_end'):r[k]=float(r[k])
    return rows
