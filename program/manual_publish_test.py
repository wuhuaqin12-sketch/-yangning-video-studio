import sys,threading,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from media import run,executable,probe
from publish import compose
from PIL import Image
p=Path(tempfile.mkdtemp(prefix='yangning-publish-test-'));c=threading.Event()
run([executable('ffmpeg'),'-v','error','-y','-f','lavfi','-i','testsrc2=size=360x640:rate=15:duration=3','-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','libx264','-c:a','aac','-shortest',str(p/'optimized.mp4')],c)
Image.new('RGB',(500,800),(30,60,65)).save(p/'背景图.png')
srt='1\n00:00:00,100 --> 00:00:01,400\nLatest subtitle at original erased area\n\n2\n00:00:01,500 --> 00:00:02,900\nLong subtitle checks automatic wrapping in the selected original subtitle region\n'
(p/'latest.srt').write_text(srt)
opts=dict(video=str(p/'optimized.mp4'),srt=str(p/'latest.srt'),background=str(p/'背景图.png'),output=str(p),title='Beyond appearances',font='DejaVu Serif',title_font='DejaVu Serif')
a=compose(opts,c,print,preview=True);print('PREVIEW',a)
b=compose(opts,c,print);print('OUTPUT',b)
assert (Path(b).parent/'subtitles.srt').read_bytes()==(p/'latest.srt').read_bytes()
info=probe(b,c);v=next(x for x in info['streams'] if x['codec_type']=='video');assert (v['width'],v['height'])==(1080,1920)
# copied AAC packet data must be identical: no new speed/pauses or voice changes.
for src,name in [(opts['video'],'before.aac'),(b,'after.aac')]:
 run([executable('ffmpeg'),'-v','error','-y','-i',src,'-map','0:a:0','-c','copy',str(p/name)],c)
assert (p/'before.aac').read_bytes()==(p/'after.aac').read_bytes()
try:compose({**opts,'subtitle_y':99},c,preview=True)
except ValueError:pass
else:raise AssertionError('invalid layout accepted')
c.set()
try:compose(opts,c)
except Exception as e:assert e.__class__.__name__=='Cancelled'
else:raise AssertionError('cancellation failed')
print('PASS: render, final SRT, exact audio preservation, bounds, cancellation')
