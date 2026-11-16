"""Bounded-memory music/voice mixing with a physical, full-length PCM clock.

Do not rely on sidechain/framesync EOF propagation, which differs across FFmpeg
builds. Speech samples are placed intact; music never ends at the last phrase.
"""
import math
from pathlib import Path
import numpy as np
from media import run,executable,Cancelled

RATE=48000

def mix(voice,music,segments,duration,gain,folder,cancel,progress):
    folder=Path(folder);voice_raw=folder/'opening_voice_source.f32';music_raw=folder/'opening_music_source.f32'
    for source,dest in ((voice,voice_raw),(music,music_raw)):
        run([executable('ffmpeg'),'-v','error','-y','-i',str(source),'-vn','-ar',str(RATE),'-ac','2','-f','f32le',str(dest)],cancel)
    samples=round(duration*RATE)
    if samples<1:raise ValueError('片头时长无效。')
    if music_raw.stat().st_size//8+round(.12*RATE)<samples:
        raise ValueError('片头音乐实际解码长度不足，已停止，避免把缺失音乐填成无声。')
    original=np.memmap(voice_raw,dtype=np.float32,mode='r').reshape(-1,2)
    background=np.memmap(music_raw,dtype=np.float32,mode='r').reshape(-1,2)
    placed=np.memmap(folder/'opening_voice_placed.f32',dtype=np.float32,mode='w+',shape=(samples,2));placed[:]=0
    for a,b,start in segments:
        if cancel.is_set():raise Cancelled('已停止')
        left=max(0,round(a*RATE));right=min(len(original),round(b*RATE));target=round(start*RATE)
        count=max(0,right-left)
        if target<0 or target+count>samples+2:raise ValueError('片头配音无法完整放入，未截断声音。')
        count=min(count,samples-target);placed[target:target+count]=original[left:left+count]
    placed.flush()
    progress('正在混合片头背景音乐与配音，保留完整音乐尾部')
    output=folder/'opening_music_voice_mix.f32';last_gain=1.
    with output.open('wb') as stream:
        for start in range(0,samples,480):
            if cancel.is_set():raise Cancelled('已停止')
            stop=min(samples,start+480);v=np.asarray(placed[start:stop]);m=np.zeros_like(v)
            n=max(0,min(stop,len(background))-start)
            if n:m[:n]=background[start:start+n]
            rms=float(np.sqrt(np.mean(v.astype(np.float64)**2)))
            target=min(1.,(max(rms,.025)/.025)**(-.8))
            time_constant=.02 if target<last_gain else .3
            end_gain=target+(last_gain-target)*math.exp(-(stop-start)/RATE/time_constant)
            envelope=np.linspace(last_gain,end_gain,stop-start,endpoint=False,dtype=np.float32)[:,None]
            stream.write((v+m*float(gain)*envelope).astype(np.float32).tobytes());last_gain=end_gain
    del placed,original,background
    if output.stat().st_size!=samples*8:raise RuntimeError('片头混音样本数量检查失败。')
    return output
