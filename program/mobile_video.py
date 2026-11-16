"""One 8-bit AVC/AAC export contract for covers and all video segments."""
from pathlib import Path
from media import probe

def encode_args():
    return ['-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p',
            '-profile:v','high','-level:v','4.1','-tag:v','avc1','-threads','2',
            '-c:a','aac','-profile:a','aac_low','-ar','48000','-ac','2','-b:a','192k',
            '-video_track_timescale','90000','-movflags','+faststart']

def inspect(path,cancel):
    streams=probe(path,cancel)['streams']
    v=next(s for s in streams if s['codec_type']=='video')
    a=next(s for s in streams if s['codec_type']=='audio')
    ok=(v['codec_name']=='h264' and v['pix_fmt']=='yuv420p' and v.get('codec_tag_string')=='avc1'
        and v.get('level',999)<=41 and a['codec_name']=='aac' and int(a['sample_rate'])==48000
        and a.get('channels')==2)
    atoms=[]
    with Path(path).open('rb') as f:
        size=Path(path).stat().st_size
        while f.tell()<size:
            at=f.tell();h=f.read(8)
            if len(h)!=8:break
            n=int.from_bytes(h[:4],'big');kind=h[4:].decode('ascii',errors='replace')
            if n==1:n=int.from_bytes(f.read(8),'big')
            if n==0:n=size-at
            if n<8:break
            atoms.append(kind);f.seek(at+n)
    faststart='moov' in atoms and 'mdat' in atoms and atoms.index('moov')<atoms.index('mdat')
    if not ok or not faststart:raise RuntimeError('手机兼容编码校验失败，未将文件标为完成。')
    return dict(video_codec=v['codec_name'],pixel_format=v['pix_fmt'],profile=v.get('profile'),level=v.get('level'),
                codec_tag=v.get('codec_tag_string'),audio_codec=a['codec_name'],audio_channels=a['channels'],
                sample_rate=int(a['sample_rate']),faststart=faststart,device_playback_verified=False)
