"""One bounded typography frame using the same layout as the sequence export."""
import json,tempfile
from pathlib import Path
from media import probe,parse_srt
from project_vnext import normalize
from sequence_vnext import ff,compose_segment

def render(settings,sequence,mode,cancel,progress=lambda _:None):
    if mode not in ('landscape','portrait'):raise ValueError('请选择横版或竖版预览。')
    source=Path(settings['video'])
    if not source.is_file():raise ValueError('请先在主页面选择正文视频。')
    at=float(settings.get('preview_time',1));duration=float(probe(source,cancel)['format']['duration'])
    if not 0<=at<duration:raise ValueError('排版预览时间超出正文视频。')
    output=Path(settings['output']);output.mkdir(parents=True,exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='排版预览_',dir=output));clip=folder/'source.mp4'
    length=min(.2,duration-at)
    ff(['-ss',at,'-i',source,'-t',length,'-map','0:v:0','-map','0:a:0?','-c:v','libx264','-preset','fast','-c:a','aac',clip],cancel)
    cues=[];srt=Path(settings.get('srt',''))
    if srt.is_file():
        all_cues=parse_srt(srt);chosen=next((c for c in all_cues if c[1]<=at<c[2]),all_cues[0] if all_cues else None)
        if chosen:cues=[(chosen[0],0,length,chosen[3])]
    p=normalize(sequence);p['background']=settings.get('background','')
    video=compose_segment(str(clip),cues,settings,mode,p,folder,cancel,True,'body',repair_chinese=False,progress=progress)
    image=folder/('横版排版预览.png' if mode=='landscape' else '竖版排版预览.png')
    ff(['-i',video,'-frames:v',1,image],cancel)
    (folder/'preview_scope.json').write_text(json.dumps(dict(mode=mode,scope='typography_only',speech_alignment=False,subtitle_removal=False,full_export=False),ensure_ascii=False),encoding='utf8')
    return str(image)
