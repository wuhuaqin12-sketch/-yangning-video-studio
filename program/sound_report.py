"""Source-based sound audit; signal attenuation is not semantic noise detection."""
import csv,json,math
from pathlib import Path
import numpy as np

def load_reference(path,duration):
    from media import parse_srt
    path=Path(path).resolve()
    if not path.is_file():raise ValueError('请选择有效的降噪对应字幕 SRT。')
    cues=parse_srt(path)
    if cues[-1][2]>duration+.05:
        raise ValueError('降噪对应字幕超过当前音频时长，请选择这段音频的时间轴；未按错误时间轴静音。')
    return dict(reference_path=str(path),reference_cues=cues,reference_checks=['utf8_srt','ordered_non_overlapping','within_audio_duration'],reference_timing_verified=False)

def attenuation(before,after,rate,peak_gain=1.):
    """100ms RMS windows, >=6dB drop for >=300ms; do not label as noise."""
    step=max(1,round(rate*.1));flags=[];drops=[]
    for a in range(0,len(before),step):
        x=np.asarray(before[a:a+step],dtype=np.float64)
        y=np.asarray(after[a:a+step],dtype=np.float64)/peak_gain
        xx=float(np.mean(x*x));yy=float(np.mean(y*y))
        db=10*math.log10(max(xx,1e-20)/max(yy,1e-20))
        flags.append(xx>=1e-6 and db>=6);drops.append(db)
    e=np.diff(np.r_[False,flags,False].astype(int));rows=[]
    for a,b in zip(np.where(e==1)[0],np.where(e==-1)[0]):
        start=a*step/rate;end=min(len(before),b*step)/rate
        if end-start<.3-1e-9:continue
        rows.append(dict(start=start,end=end,seconds=end-start,mean_drop_db=round(float(np.mean(drops[a:b])),2),classification='signal_attenuation_only'))
    return rows

def output_parts(start,end,events,speed=1.):
    """Split at cuts/insertions; never report deleted material as an output span."""
    pieces=[(start,end)]
    for e in events:
        if e['kind']!='cut':continue
        a,b=e['start'],e['end'];new=[]
        for l,r in pieces:
            if b<=l or a>=r:new.append((l,r));continue
            if l<a:new.append((l,a))
            if b<r:new.append((b,r))
        pieces=new
    for e in events:
        if e['kind']=='add':
            t=e['start'];pieces=[z for a,b in pieces for z in ([(a,t),(t,b)] if a<t<b else [(a,b)])]
    def time(t,after):
        cuts=sum(max(0,min(t,e['end'])-e['start']) for e in events if e['kind']=='cut')
        adds=sum(e['seconds'] for e in events if e['kind']=='add' and (e['start']<=t if after else e['start']<t))
        return (t-cuts+adds)/speed
    return [dict(start=time(a,True),end=time(b,False),seconds=(b-a)/speed) for a,b in pieces if b>a]

def clock(t):
    t=round(t*1000);h,t=divmod(t,3600000);m,t=divmod(t,60000);s,ms=divmod(t,1000)
    return f'{h:02}:{m:02}:{s:02}.{ms:03}'

def write_report(folder,processing,duration,events=(),mutes=(),speed=1.,source='',timeline='原素材时间轴',output_duration=None,cues=(),subtitle_reference=''):
    folder=Path(folder);events=list(events);processing=processing or {'enabled':False,'mode':'original_audio'}
    if not math.isfinite(speed) or speed<=0:raise ValueError('报告倍速无效')
    rows=[]
    cues=list(cues)
    def row(kind,a,b,reason='',extra=None):
        item=dict(kind=kind,source_start=a,source_end=b,source_seconds=b-a,output_intervals=output_parts(a,b,events,speed),reason=reason)
        if extra:item.update(extra)
        rows.append(item)
    if processing.get('denoise_enabled'):
        row('denoise',0,duration,'整段应用降噪滤镜；不代表每一处都识别为噪音')
    if processing.get('separation'):
        row('separation',0,duration,'整段人声分离；不保证分开其他讲话者')
    for e in processing.get('attenuated_intervals',[]):
        row('attenuation',e['start'],min(duration,e['end']),'处理后信号减弱，供定位试听；不等同已识别或彻底清除噪音',{'mean_drop_db':e['mean_drop_db']})
    for e in mutes:
        row('mute',e['start'],e['end'],e.get('reason') or '用户选择静音，保留该段时长',{'fade_start':e.get('fade_start',e['start']),'fade_end':e.get('fade_end',e['end'])})
    for index,e in enumerate(events):
        if e['kind']=='cut':row('cut',e['start'],e['end'],e.get('reason') or '剪掉片段')
        elif e['kind']=='add':
            t=e['start'];at=(t-sum(max(0,min(t,v['end'])-v['start']) for v in events if v['kind']=='cut')+sum(v['seconds'] for j,v in enumerate(events) if v['kind']=='add' and (v['start']<t or v['start']==t and j<index)))/speed
            rows.append(dict(kind='inserted_silence',source_start=t,source_end=t,source_seconds=0,output_intervals=[dict(start=at,end=at+e['seconds']/speed,seconds=e['seconds']/speed)],reason=e.get('reason') or '新增静音停顿'))
    for item in rows:
        if item['kind'] not in ('denoise','separation'):
            a,b=item['source_start'],item['source_end']
            item['subtitle_text']=' / '.join(str(c[3]) for c in cues if c[1] < max(b,a+.001) and c[2]>a)
            if not item['subtitle_text']:
                previous=[c for c in cues if c[2]<=a];following=[c for c in cues if c[1]>=b]
                item['previous_subtitle']=str(max(previous,key=lambda c:c[2])[3]) if previous else ''
                item['next_subtitle']=str(min(following,key=lambda c:c[1])[3]) if following else ''
    for item in rows:item['output_seconds']=sum(p['seconds'] for p in item['output_intervals'])
    result=dict(subtitle_reference=subtitle_reference,subtitle_comparison='time_overlap_only_no_speech_recognition',schema=1,source=source,source_timeline=timeline,source_duration=duration,output_duration=output_duration if output_duration is not None else (duration-sum(e['end']-e['start'] for e in events if e['kind']=='cut')+sum(e['seconds'] for e in events if e['kind']=='add'))/speed,speed=speed,processing=processing,entries=rows,hearing_review_complete=False,all_noise_removed_certified=False,note='原始时间与成片时间分别列出；音量衰减是客观信号变化，不是语义噪音识别。没有记录的静音不代表已处理。自动报告不代替逐句试听。')
    (folder/'声音处理明细.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    labels=dict(denoise='整段降噪',separation='人声分离',attenuation='明显减弱·待试听',mute='静音',cut='剪掉',inserted_silence='新增静音停顿')
    mode_name={'v11_deep':'V11 加强降噪','v11':'温和降噪','original_audio':'未启用降噪','separation_only':'仅人声分离'}.get(processing.get('mode'),'未启用降噪')
    lines=['声音处理明细',f'来源：{source}',f'原始时间基准：{timeline}',f'原始时长：{clock(duration)}；成片时长：{clock(result["output_duration"])}；倍速：{speed:g}',f'降噪：{mode_name}；人声分离：'+('已执行' if processing.get('separation') else '未执行'),result['note'],'字幕：'+(subtitle_reference or '未提供')+'；下列对应文字仅按时间段读取，未与讲话逐字比对。','','序号 | 操作 | 原始起止时间 | 原始/成片持续秒数 | 成片起止时间 | 说明']
    csvrows=[]
    for i,e in enumerate(rows,1):
        out=' / '.join(clock(p['start'])+'—'+clock(p['end']) for p in e['output_intervals']) or '已剪去，成片无此区间'
        detail=e['reason']
        if e.get('subtitle_text'):detail+='；对应字幕：'+e['subtitle_text'].replace('\n',' ')
        if e.get('previous_subtitle'):detail+='；前一句：'+e['previous_subtitle'].replace('\n',' ')
        if e.get('next_subtitle'):detail+='；后一句：'+e['next_subtitle'].replace('\n',' ')
        if 'mean_drop_db' in e:detail+=f'；平均减弱{e["mean_drop_db"]:.2f}dB（已排除整体峰值限幅增益）'
        if e['kind']=='mute':detail+=f'；边界淡化涉及{clock(e["fade_start"])}—{clock(e["fade_end"])}'
        lines.append(f'{i} | {labels[e["kind"]]} | {clock(e["source_start"])}—{clock(e["source_end"])} | {e["source_seconds"]:.3f}/{e["output_seconds"]:.3f} | {out} | {detail}')
        csvrows.append([i,labels[e['kind']],e['source_start'],e['source_end'],e['source_seconds'],e['output_seconds'],out,detail])
    if not rows:lines.append('未启用降噪、人声分离，也没有静音或剪掉记录。')
    if not any(e['kind']=='mute' for e in rows):lines.append('\n局部静音：无。报告不会把自然停顿或滤镜造成的低音量冒充手动静音。')
    (folder/'声音处理明细.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8-sig')
    with (folder/'声音处理明细.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['序号','操作','原始开始秒','原始结束秒','原始持续秒','成片持续秒','成片起止时间','说明']);w.writerows(csvrows)
    return result
