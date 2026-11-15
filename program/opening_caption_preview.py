"""Bounded original-video preview of one translated title, without full synthesis."""
import json,math,shutil,tempfile
from pathlib import Path
from project_vnext import defaults,normalize
from media import executable,run,probe

def render(source,settings,language,prefix,output,cancel,progress=lambda _:None):
    if prefix not in ('opening_title','opening_topic'):raise ValueError('译名分组选项无效。')
    if not Path(source).is_file():raise ValueError('请先导入含原文字的视频。')
    # Irrelevant segments, narration and the other title cannot block this preview.
    p=defaults();p.update({k:v for k,v in settings.items() if k.startswith(prefix+'_') and k in p});p=normalize(p)
    info=probe(source,cancel);stream=next((s for s in info['streams'] if s['codec_type']=='video'),None)
    if stream is None:raise ValueError('所选素材没有视频画面。')
    total=float(info['format']['duration']);start=p[prefix+'_start'];end=min(total,p[prefix+'_end'])
    if not 0<=start<end:raise ValueError('译名显示范围超出当前视频，请检查开始和结束时间。')
    begin=max(0,start-.5);length=min(15,total-begin,end-begin+.5)
    if not math.isfinite(length) or length<=0:raise ValueError('译名预览时长无效。')
    from engine import square_pixel_stream
    stream=square_pixel_stream(stream)
    rotation=int(stream.get('tags',{}).get('rotate',0))
    for side in stream.get('side_data_list',[]):
        if 'rotation' in side:rotation=int(side['rotation'])
    w,h=int(stream['width']),int(stream['height'])
    if abs(rotation)%180==90:w,h=h,w
    factor=min(1,1280/max(w,h));w=max(2,int(w*factor)//2*2);h=max(2,int(h*factor)//2*2)
    if not str(output).strip():raise ValueError('请选择预览保存文件夹。')
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='TitlePreview_',dir=output));ass=folder/'title_preview.ass'
    p[prefix+'_start']=start-begin;p[prefix+'_end']=min(end-begin,length)
    from publish import make_ass
    from opening_caption import add_ass
    make_ass(ass,[],{'title':'','video_width':100,'video_height':100,'subtitle_area':'video'},{'width':w,'height':h},length,w,h)
    add_ass(ass,p,language,(0,0,w,h),length,prefix)
    fonts=Path(__file__).parent/'fonts'
    if fonts.is_dir():shutil.copytree(fonts,folder/'fonts')
    dest=folder/'title_preview.mp4'
    progress(f'仅生成这组译文的 {length:.1f} 秒原声预览，不处理配音或片尾')
    run([executable('ffmpeg'),'-nostdin','-v','error','-y','-ss',str(begin),'-i',str(source),'-t',str(length),'-map','0:v:0','-map','0:a:0?','-vf',f"scale={w}:{h},setsar=1,ass=filename='title_preview.ass':fontsdir=fonts",'-c:v','libx264','-preset','fast','-crf','20','-c:a','aac','-movflags','+faststart',str(dest)],cancel,cwd=folder)
    (folder/'preview_scope.json').write_text(json.dumps(dict(scope='one_translated_title',prefix=prefix,start=begin,seconds=length,original_audio=True,narration=False,ending=False,full_preview_approved=False),ensure_ascii=False,indent=2),encoding='utf8')
    return str(dest)
