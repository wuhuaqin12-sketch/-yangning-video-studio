"""Five-minute cross-segment decode/seek fixture, using the actual final encoder."""
import json,os,sys,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'program'))
from sequence_vnext import ff,concat_clips
from mobile_video import inspect
from media import probe

def main():
    root=Path(os.environ['RUNNER_TEMP'])/'YangNingFormalAcceptance';root.mkdir(exist_ok=True)
    stop=threading.Event();clips=[]
    for name,duration,color in [('cover',3,'blue'),('body',290,'green'),('ending',7,'red')]:
        p=root/(name+'.mp4')
        ff(['-f','lavfi','-i',f'color={color}:s=360x640:r=30:d={duration}',
            '-f','lavfi','-i',f'sine=frequency=660:duration={duration}',
            '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv444p' if name=='cover' else 'yuv420p',
            '-video_track_timescale','90000' if name=='cover' else '15360','-c:a','aac','-ar','48000','-ac','2',p],stop)
        clips.append(p)
    output=root/'phone-playback-sample.mp4';concat_clips(clips,output,root,stop)
    info=inspect(output,stop);duration=float(probe(output,stop)['format']['duration']);assert abs(duration-300)<.1
    ff(['-xerror','-i',output,'-f','null','-'],stop)
    from playwright.sync_api import sync_playwright
    edge=Path(os.environ['PROGRAMFILES(X86)'])/'Microsoft/Edge/Application/msedge.exe'
    if not edge.exists():edge=Path(os.environ['PROGRAMFILES'])/'Microsoft/Edge/Application/msedge.exe'
    pagefile=root/'playback.html';pagefile.write_text('<video id="v" muted controls src="'+output.as_uri()+'"></video><canvas id="c"></canvas>',encoding='utf8')
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=str(edge),headless=True,args=['--allow-file-access-from-files','--autoplay-policy=no-user-gesture-required'])
        page=browser.new_page();page.goto(pagefile.as_uri());page.wait_for_function('document.getElementById("v").readyState>=2',timeout=60000)
        for at,channel in ((.3,2),(3.5,1),(299,0)):
            color=page.evaluate('''async at=>{
              const v=document.getElementById('v'),c=document.getElementById('c');
              await new Promise((resolve,reject)=>{v.addEventListener('seeked',resolve,{once:true});v.currentTime=at;setTimeout(()=>reject(new Error('seek timed out')),15000);});
              c.width=v.videoWidth;c.height=v.videoHeight;const x=c.getContext('2d');x.drawImage(v,0,0);
              return Array.from(x.getImageData(100,100,1,1).data).slice(0,3);
            }''',at)
            assert color.index(max(color))==channel,(at,color)
        page.screenshot(path=str(root/'mobile-browser-seek.png'));browser.close()
    info.update(duration=duration,windows_edge_seek_verified=True,physical_phone_verified=False)
    (root/'mobile-compatibility.json').write_text(json.dumps(info,indent=2),encoding='utf8')
    print('FIVE_MINUTE_MOBILE_CONTRACT_AND_BROWSER_SEEK_PASS',flush=True)

if __name__=='__main__':main()
