"""Locate an existing title with local OCR; add an editable translated line."""
import functools,math,re,tempfile
from pathlib import Path
import numpy as np
from media import executable,run,probe,Cancelled,stamp

def localized_title(text,language,original='金刚经讲义'):
    if text.strip():return text.strip()
    if normalized(original)=='金刚经讲义':mapping={'ja':'『金剛経』講義','en':'Lectures on the Diamond Sutra'}
    elif normalized(original)=='经题':mapping={'ja':'経題','en':'Title of the Sutra'}
    else:raise ValueError('其他标题请填写对应语言译名，软件不会猜测翻译。')
    if language not in mapping:raise ValueError('请填写当前语言的片头译名；软件不调用翻译或配音服务。')
    return mapping[language]

def normalized(text):
    text=text.translate(str.maketrans('剛經講義題','刚经讲义题'))
    return re.sub(r'[^\w\u4e00-\u9fff]','',text).lower()

@functools.lru_cache(maxsize=1)
def engine():
    try:from rapidocr import RapidOCR
    except ImportError as e:raise RuntimeError('自动定位缺少本地OCR，请运行测试安装器补齐依赖；仍可手动填写位置和时间。') from e
    return RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads':1,'EngineConfig.onnxruntime.inter_op_num_threads':1,'EngineConfig.onnxruntime.use_cuda':False})

def detect(source,target,start,end,cancel,progress=lambda _:None):
    if not normalized(target):raise ValueError('请填写原中文标题，用于匹配OCR结果。')
    if not 0<=start<end or end-start>120:raise ValueError('自动定位范围须在120秒以内，请先缩小到片头标题出现的位置。')
    import cv2
    total=float(probe(source,cancel)['format']['duration']);end=min(end,total)
    if start>=end:raise ValueError('定位范围超出视频。')
    samples=min(12,max(1,math.ceil(end-start)));step=(end-start)/samples
    target=normalized(target);found=[];recognizer=engine()
    with tempfile.TemporaryDirectory(prefix='title_ocr_') as d:
        for i in range(samples):
            if cancel.is_set():raise Cancelled('已停止')
            time=start+(i+.5)*step;image=Path(d)/'frame.png'
            run([executable('ffmpeg'),'-nostdin','-v','error','-y','-ss',str(time),'-i',str(source),'-frames:v','1',str(image)],cancel)
            frame=cv2.imread(str(image));result=recognizer(frame,use_cls=False)
            texts=list(result.txts) if result.txts is not None else [];scores=list(result.scores) if result.scores is not None else [];boxes=result.boxes
            chosen=[]
            if boxes is not None:
                for j,text in enumerate(texts):
                    t=normalized(text)
                    if scores[j]>=.65 and (target in t or (len(t)>=1 and t in target)):chosen.append(j)
                if target not in ''.join(normalized(texts[j]) for j in chosen):chosen=[]
            if chosen:
                points=np.concatenate([boxes[j] for j in chosen]);h,w=frame.shape[:2]
                found.append(dict(time=time,x=float((points[:,0].min()+points[:,0].max())/2/w*100),y=float((points[:,1].max()+max(12,h*.035))/h*100),recognized=' '.join(texts[j] for j in chosen)))
            progress(f'片头标题本地定位：{i+1}/{samples} 帧'+('，已找到匹配' if chosen else ''))
    if not found:raise ValueError('未识别到匹配的原中文标题。请核对标题文字、缩小出现时间范围，或手动填写位置；不会猜测位置。')
    return dict(opening_title_x=round(float(np.median([v['x'] for v in found])),2),opening_title_y=round(min(92,float(np.median([v['y'] for v in found]))),2),opening_title_start=round(max(start,min(v['time'] for v in found)-step/2),3),opening_title_end=round(min(end,max(v['time'] for v in found)+step/2),3),recognized=found[0]['recognized'])

def add_ass(path,p,language,video_box,duration,prefix='opening_title'):
    from publish_style import fit_lines
    if prefix!='opening_title':p={**p,**{'opening_title_'+suffix:p[prefix+'_'+suffix] for suffix in ('text','original','start','end','x','y','size')}}
    text=localized_title(p['opening_title_text'],language,p['opening_title_original'])
    if len(text)>200:raise ValueError('片头译名过长，请缩短。')
    vx,vy,vw,vh=video_box;x=vx+vw*p['opening_title_x']/100;y=vy+vh*p['opening_title_y']/100
    end=min(duration,p['opening_title_end']);start=p['opening_title_start']
    if start>=end:raise ValueError('片头译名范围超出当前片头/视频时长。')
    size=max(18,round(p['opening_title_size']*vh/1080));available=min(vw*.88,2*min(x-vx,vx+vw-x))
    room=vy+vh-y-12
    if room<size*1.2:raise ValueError('原中文标题下方没有足够空间，请把译名位置上移或减小字号。')
    size,lines=fit_lines(text,size,available,room,True,leading=1.25)
    if size<18:raise ValueError('片头译名放不下，请缩短文字或调整位置。')
    safe=lambda s:s.replace('\\','／').replace('{','｛').replace('}','｝')
    rendered=r'\N'.join(safe(''.join(c for _,c in row)) for row in lines)
    data=Path(path).read_text(encoding='utf-8-sig')
    style_name='OpeningTranslated' if prefix=='opening_title' else 'OpeningTopicTranslated'
    style=f'Style: {style_name},Noto Serif CJK JP,{size},&H00FFFFFF,&H00FFFFFF,&H00303030,&HFF000000,0,0,0,0,100,100,0,0,1,1,0,8,0,0,0,1\n'
    data=data.replace('[Events]',style+'[Events]')
    data+=f'Dialogue: 4,{stamp(start,True)},{stamp(end,True)},{style_name},,0,0,0,,{{\\an8\\pos({x:.1f},{y:.1f})}}{rendered}\n'
    Path(path).write_text(data,encoding='utf-8-sig')
