"""Reproducible synthetic fixtures; never uses user media."""
import subprocess
from pathlib import Path
from PIL import Image
root=Path(__file__).resolve().parents[1]/'dist/samples';root.mkdir(parents=True,exist_ok=True)
for name,color,freq,duration in [('intro','blue',330,2),('body','green',440,2),('outro','red',880,2),('body20','green',440,20)]:
 subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'color={color}:s=320x180:r=24:d={duration}','-f','lavfi','-i',f'sine=frequency={freq}:sample_rate=48000:duration={duration}','-c:v','libx264','-pix_fmt','yuv420p','-preset','ultrafast','-c:a','aac','-ac','2','-b:a','96k','-movflags','+faststart',str(root/(name+'.mp4'))],check=True)
for name,freq,duration in [('voice',660,2),('voice20',660,20),('music2',220,2),('intro_voice2',550,2)]:
 subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'sine=frequency={freq}:sample_rate=48000:duration={duration}','-c:a','pcm_s16le',str(root/(name+'.wav'))],check=True)
(root/'body.srt').write_text('1\n00:00:00,100 --> 00:00:01,900\n金剛経 · 手机本机合成测试\n',encoding='utf8')
Image.new('RGB',(960,540),'gold').save(root/'cover_landscape.png');Image.new('RGB',(540,960),'gold').save(root/'cover_portrait.png');Image.new('RGB',(540,960),'navy').save(root/'background.png')
