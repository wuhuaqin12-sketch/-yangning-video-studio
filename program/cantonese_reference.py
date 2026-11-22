"""Map Chinese reference speech timings onto Cantonese display subtitles.

The two SRTs use the original video's clock. Chinese cues are aligned to the
narration; Cantonese cues may join or split them, but their source spans must
overlap. Never silently use unrelated cue numbers or approximate by line count.
"""
import json,math
from pathlib import Path

def remap(chinese,aligned,yue,folder):
    if len(chinese)!=len(aligned) or [c[0] for c in chinese]!=[c[0] for c in aligned]:
        raise ValueError('中文参考 SRT 与定位结果的编号不一致。')
    if not chinese or not yue:raise ValueError('中文或粤语 SRT 为空。')
    for name,cues in (('中文',chinese),('粤语',yue)):
        if any(b<=a or not all(map(math.isfinite,(a,b))) for _,a,b,_ in cues):
            raise ValueError(name+' SRT 存在无效时间。')
        if any(b[1]<a[1] or b[1]<a[2]-.01 for a,b in zip(cues,cues[1:])):
            raise ValueError(name+' SRT 顺序或时间重叠，请先修正。')
    if any(b[1]<a[1] or b[1]<a[2]-.01 for a,b in zip(aligned,aligned[1:])):
        raise ValueError('中文配音定位结果重叠，不能映射粤语字幕。')
    def convert(t):
        for j,(_,start,end,_) in enumerate(chinese):
            if start<=t<=end:
                v=aligned[j]
                return v[1]+(t-start)/(end-start)*(v[2]-v[1])
            if j+1<len(chinese) and end<t<chinese[j+1][1]:
                left,right=aligned[j][2],aligned[j+1][1]
                return left+(t-end)/(chinese[j+1][1]-end)*(right-left)
        raise ValueError(f'粤语字幕时间 {t:.3f}s 不在中文参考范围，请校对视频时间轴。')
    output=[];mapping=[]
    for ident,start,end,text in yue:
        matched=[c for c in chinese if min(end,c[2])-max(start,c[1])>.001]
        coverage=sum(max(0,min(end,c[2])-max(start,c[1])) for c in matched)/(end-start)
        if coverage<.5:
            raise ValueError(f'粤语第{ident}条与中文参考覆盖仅 {coverage:.0%}，请检查错位或修正分句时间。')
        a,b=convert(start),convert(end)
        if b<=a or (output and a<output[-1][2]-.01):
            raise ValueError(f'粤语第{ident}条映射后出现重叠或零时长，请校对分句。')
        output.append((ident,a,b,text))
        mapping.append(dict(yue_id=ident,chinese_ids=[c[0] for c in matched],coverage=round(coverage,3),start=a,end=b))
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    (folder/'cantonese_cue_mapping.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2),encoding='utf8')
    return output
