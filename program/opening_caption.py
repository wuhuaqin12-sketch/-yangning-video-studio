"""Locate an existing title with local OCR; add an editable translated line."""
import functools,math,re,tempfile
from pathlib import Path
import numpy as np
from media import executable,run,probe,Cancelled,stamp

def localized_title(text,language,original='金刚经讲义'):
    if text.strip():return text.strip()
    if normalized(original)=='金刚经讲义':mapping={'ja':'『金剛経』講義','en':'Lectures on the Diamond Sutra'}
    elif normalized(original)=='经题':mapping={'ja':'経題','en':'Title of the Sutra'}
    elif normalized(original)=='释迦牟尼佛':mapping={'ja':'釈迦牟尼仏','en':'Shakyamuni Buddha'}
    else:raise ValueError('其他标题请填写对应语言译名，软件不会猜测翻译。')
    if language not in mapping:raise ValueError('请填写当前语言的片头译名；软件不调用翻译或配音服务。')
    return mapping[language]

def normalized(text):
    text=text.translate(str.maketrans('剛經講義題釋','刚经讲义题释'))
    return re.sub(r'[^\w\u4e00-\u9fff]','',text).lower()

@functools.lru_cache(maxsize=1)
def engine():
    try:from rapidocr import RapidOCR
    except ImportError as e:raise RuntimeError('自动定位缺少本地OCR，请运行测试安装器补齐依赖；仍可手动填写位置和时间。') from e
    return RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads':1,'EngineConfig.onnxruntime.inter_op_num_threads':1,'EngineConfig.onnxruntime.use_cuda':False})

def sample_style(frame,points,characters):
    """Estimate ink colour/visible glyph height, never claim to identify a font."""
    import cv2
    h,w=frame.shape[:2];x0=max(0,int(points[:,0].min()));x1=min(w,int(points[:,0].max())+1)
    y0=max(0,int(points[:,1].min()));y1=min(h,int(points[:,1].max())+1)
    patch=frame[y0:y1,x0:x1];gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY)
    border=frame[max(0,y0-4):min(h,y1+4),max(0,x0-4):min(w,x1+4)]
    background=float(np.median(cv2.cvtColor(border,cv2.COLOR_BGR2GRAY)))
    threshold,_=cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    groups=[gray<=threshold,gray>threshold]
    candidates=[m for m in groups if .005<float(np.mean(m))<.85]
    if not candidates:raise ValueError('无法可靠取样原字颜色，请手动设置。')
    ink=max(candidates,key=lambda m:abs(float(np.median(gray[m]))-background))
    b,g,r=np.median(patch[ink],axis=0).astype(int)
    vertical=(y1-y0)>1.35*(x1-x0) and characters<=10
    heights=[];firsts=[];n=max(1,characters)
    for i in range(n):
        cell=ink[round(i*ink.shape[0]/n):round((i+1)*ink.shape[0]/n),:] if vertical else ink[:,round(i*ink.shape[1]/n):round((i+1)*ink.shape[1]/n)]
        if not cell.size:continue
        rows=np.flatnonzero(np.sum(cell,axis=1)>=max(2,cell.shape[1]*.04))
        if len(rows)>2:
            heights.append(int(rows[-1]-rows[0]+1))
            if vertical:firsts.append(round(i*ink.shape[0]/n)+int(rows[0]))
    char_height=float(np.median(heights)) if heights else (y1-y0)/n if vertical else y1-y0
    if vertical:
        x=(x1+max(12,w*.015)+char_height/2)/w*100;y=(y0+(firsts[0] if firsts else 0))/h*100
    else:x=(x0+x1)/2/w*100;y=(y1+max(12,h*.035))/h*100
    advance=float(np.median(np.diff(firsts))) if len(firsts)>1 else char_height*1.35
    return dict(x=min(95,x),y=min(92,y),color=f'#{r:02X}{g:02X}{b:02X}',reference_height=char_height/h*100,reference_advance=advance/h*100,orientation='vertical' if vertical else 'horizontal')

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
                style=sample_style(frame,points,len(target))
                found.append(dict(time=time,**style,recognized=' '.join(texts[j] for j in chosen)))
            progress(f'片头标题本地定位：{i+1}/{samples} 帧'+('，已找到匹配' if chosen else ''))
    if not found:raise ValueError('未识别到匹配的原中文标题。请核对标题文字、缩小出现时间范围，或手动填写位置；不会猜测位置。')
    colors=np.asarray([[int(v['color'][j:j+2],16) for j in (1,3,5)] for v in found]);color='#'+''.join(f'{int(c):02X}' for c in np.median(colors,axis=0))
    return dict(opening_title_x=round(float(np.median([v['x'] for v in found])),2),opening_title_y=round(float(np.median([v['y'] for v in found])),2),opening_title_start=round(max(start,min(v['time'] for v in found)-step/2),3),opening_title_end=round(min(end,max(v['time'] for v in found)+step/2),3),opening_title_color=color,opening_title_reference_height=round(float(np.median([v['reference_height'] for v in found])),3),opening_title_reference_advance=round(float(np.median([v['reference_advance'] for v in found])),3),opening_title_orientation=max(('horizontal','vertical'),key=lambda s:sum(v['orientation']==s for v in found)),opening_title_match_size=True,recognized=found[0]['recognized'])

def add_ass(path,p,language,video_box,duration,prefix='opening_title'):
    from publish_style import fit_lines,ass_colour
    from PIL import ImageFont
    if prefix!='opening_title':p={**p,**{'opening_title_'+suffix:p[prefix+'_'+suffix] for suffix in ('text','original','start','end','x','y','size','font','color','orientation','match_size','reference_height','reference_advance')}}
    text=localized_title(p['opening_title_text'],language,p['opening_title_original'])
    if len(text)>200:raise ValueError('片头译名过长，请缩短。')
    vx,vy,vw,vh=video_box;x=vx+vw*p['opening_title_x']/100;y=vy+vh*p['opening_title_y']/100
    end=min(duration,p['opening_title_end']);start=p['opening_title_start']
    if start>=end:raise ValueError('片头译名范围超出当前片头/视频时长。')
    font_name=p['opening_title_font'];color=p['opening_title_color']
    ref=p['opening_title_reference_height'];match=p['opening_title_match_size'] and ref>0
    font_path=Path(__file__).parent/'fonts'/('YujiBoku-Regular.ttf' if font_name=='Yuji Boku' else 'NotoSerifCJKjp-Regular.otf')
    font=ImageFont.truetype(str(font_path),100);sample=next((c for c in text if c.isalnum()),'経');box=font.getbbox(sample);asc,desc=font.getmetrics()
    ratio=max(.1,(box[3]-box[1])/(asc+desc));wanted=vh*ref/100
    size=max(18,round(wanted/ratio)) if match else max(18,round(p['opening_title_size']*vh/1080))
    margin=box[1]*size/(asc+desc) if match else 0
    vertical=p['opening_title_orientation']=='vertical' and language in ('ja','zh','ko')
    side=p['opening_title_orientation']=='vertical' and not vertical
    available=vx+vw-x-12 if side else min(vw*.88,2*min(x-vx,vx+vw-x))
    room=vy+vh-y-12
    if room<size*1.2:raise ValueError('原中文标题下方没有足够空间，请把译名位置上移或减小字号。')
    if vertical:
        chars=[c for c in text if not c.isspace()];step=vh*p['opening_title_reference_advance']/100 if match and p['opening_title_reference_advance']>0 else (wanted if match else size*ratio)*1.35
        if y+(len(chars)-1)*step+(wanted if match else size*ratio)>vy+vh-12:raise ValueError('同字高竖排译文放不下，请移动位置、缩短文字或取消匹配字高。')
        if size*ratio>available:raise ValueError('译文宽度不足，请调整位置或字号。')
        lines=None
    else:
        try:size,lines=fit_lines(text,size,available,room,not match,leading=1.25)
        except ValueError as e:raise ValueError('按原字大小放不下译文，请调整位置、缩短译文或取消匹配字高。') from e
    if size<18:raise ValueError('片头译名放不下，请缩短文字或调整位置。')
    safe=lambda s:s.replace('\\','／').replace('{','｛').replace('}','｝')
    rendered='' if vertical else r'\N'.join(safe(''.join(c for _,c in row)) for row in lines)
    data=Path(path).read_text(encoding='utf-8-sig')
    style_name='OpeningTranslated' if prefix=='opening_title' else 'OpeningTopicTranslated'
    style=f'Style: {style_name},{font_name},{size},{ass_colour(color)},&H00FFFFFF,{ass_colour(color)},&HFF000000,0,0,0,0,100,100,0,0,1,0,0,8,0,0,0,1\n'
    data=data.replace('[Events]',style+'[Events]')
    if vertical:
        for i,c in enumerate(chars):
            char_margin=font.getbbox(c)[1]*size/(asc+desc) if match else 0
            data+=f'Dialogue: 4,{stamp(start,True)},{stamp(end,True)},{style_name},,0,0,0,,{{\\an8\\pos({x:.1f},{y+i*step-char_margin:.1f})}}{safe(c)}\n'
    else:data+=f'Dialogue: 4,{stamp(start,True)},{stamp(end,True)},{style_name},,0,0,0,,{{\\an{7 if side else 8}\\pos({x:.1f},{y-margin:.1f})}}{rendered}\n'
    Path(path).write_text(data,encoding='utf-8-sig')
