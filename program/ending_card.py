"""Optional disclaimer image: append a card or overlay the existing ending."""
from pathlib import Path
from PIL import Image,ImageOps
from media import executable,run,probe

def ff(args,cancel):return run([executable('ffmpeg'),'-nostdin','-v','error','-y',*map(str,args)],cancel)

def normalized_image(path,folder,mode):
    dest=Path(folder)/('disclaimer_image_'+mode+'.png')
    if not path or not Path(path).is_file():raise ValueError('请选择免责声明图片。')
    with Image.open(path) as im:ImageOps.exif_transpose(im).convert('RGBA').save(dest)
    return dest

def append_card(image,mode,duration,folder,cancel):
    w,h=(1920,1080) if mode=='landscape' else (1080,1920)
    image=normalized_image(image,folder,mode);out=Path(folder)/('disclaimer_'+mode+'.mp4')
    vf=f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30'
    ff(['-loop','1','-i',image,'-f','lavfi','-i',f'anullsrc=r=48000:cl=stereo:d={duration}','-vf',vf,'-t',duration,'-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',out],cancel)
    return out

def overlay(source,image,mode,duration,folder,cancel):
    info=probe(source,cancel);total=float(info['format']['duration'])
    if duration>total:raise ValueError('免责声明显示秒数超过视频长度。')
    v=next(s for s in info['streams'] if s['codec_type']=='video');w,h=v['width'],v['height']
    image=normalized_image(image,folder,mode);out=Path(folder)/('disclaimer_overlay_'+mode+'.mp4')
    # An explicitly selected overlay remains a lower card; do not replace or
    # truncate the original ending or its music with a full-screen image.
    bw,bh=int(w*.8)//2*2,int(h*.35)//2*2
    graph=f'[1:v]scale={bw}:{bh}:force_original_aspect_ratio=decrease[card];[0:v][card]overlay=(W-w)/2:H-h-40:enable=\'gte(t,{max(0,total-duration):.6f})\':shortest=1[v]'
    ff(['-i',source,'-loop','1','-i',image,'-filter_complex_threads','1','-filter_complex',graph,'-map','[v]','-map','0:a:0?','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','copy','-t',total,'-movflags','+faststart',out],cancel)
    return out
