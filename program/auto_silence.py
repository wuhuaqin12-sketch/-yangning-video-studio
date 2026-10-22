"""Shorten only long acoustically silent gaps; keep natural breathing space."""
import numpy as np
from scipy.io import wavfile

def propose(path,cues=()):
    rate,x=wavfile.read(path)
    if x.ndim==1:x=x[:,None]
    step=max(1,round(rate*.01));n=(len(x)+step-1)//step
    frames=np.pad(x,((0,n*step-len(x)),(0,0))).reshape(n,step,x.shape[1])
    rms=np.sqrt(np.mean(frames**2,axis=1)).max(axis=1)
    silent=rms<10**(-55/20)
    starts=np.flatnonzero(np.diff(np.r_[False,silent].astype(int))==1)
    ends=np.flatnonzero(np.diff(np.r_[silent,False].astype(int))==-1)+1
    duration=len(x)/rate;edits=[]
    for p,q in zip(starts,ends):
        a,b=p*step/rate,min(duration,q*step/rate)
        if a<=.011 and b>=duration-.011:continue
        if a<=.011:
            if b-a<.6:continue
            ca,cb=a,b-.15;reason='片头空白，保留0.15秒'
        elif b>=duration-.011:
            if b-a<.8:continue
            ca,cb=a+.25,b;reason='片尾空白，保留0.25秒'
        else:
            if b-a<.7:continue
            inside=any(start+.05<a and b<end-.05 for _,start,end,_ in cues)
            keep=.35 if inside else .45
            ca,cb=a+keep/2,b-keep/2;reason=f'长空白，保留{keep:g}秒自然停顿'
        if cb-ca>=.12:edits.append(dict(start=ca,end=cb,kind='cut',reason=reason))
    return edits

def merge_cuts(cuts):
    out=[]
    for e in sorted(cuts,key=lambda x:x['start']):
        if out and e['start']<=out[-1]['end']:out[-1]['end']=max(out[-1]['end'],e['end'])
        else:out.append(dict(start=e['start'],end=e['end'],kind='cut'))
    return out
