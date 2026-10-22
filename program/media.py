"""Local timeline renderer. Python standard library + FFmpeg."""
import bisect, json, math, os, re, shutil, subprocess, tempfile, wave
from pathlib import Path
from fractions import Fraction

class Cancelled(Exception): pass

def executable(name):
    local = Path(__file__).parent / 'tools' / (name + '.exe')
    found = str(local) if local.exists() else shutil.which(name)
    if not found and os.name == 'nt':
        link = Path(os.environ.get('LOCALAPPDATA','')) / 'Microsoft/WinGet/Links' / (name+'.exe')
        if link.exists(): found = str(link)
        else:
            root = Path(os.environ.get('LOCALAPPDATA','')) / 'Microsoft/WinGet/Packages'
            found = next((str(p) for p in root.glob('Gyan.FFmpeg*/**/'+name+'.exe')), None)
    if not found: raise RuntimeError('未找到 '+name+'，请先运行 install_windows.bat，或将程序放入 tools 文件夹。')
    return found

def run(args, cancel, cwd=None):
    with tempfile.TemporaryFile() as log:
        p = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, cwd=cwd, creationflags=0x08000000 if os.name=='nt' else 0)
        import time
        while p.poll() is None:
            if cancel.is_set():
                p.terminate(); p.wait(); raise Cancelled('已停止')
            time.sleep(.1)
        log.seek(0); result=log.read().decode('utf-8',errors='replace')
        if p.returncode: raise RuntimeError(result[-4000:])
        return result

def probe(path, cancel):
    return json.loads(run([executable('ffprobe'),'-v','error','-show_streams','-show_format','-of','json',str(path)],cancel))

def parse_srt(path):
    text=Path(path).read_text(encoding='utf-8-sig').replace('\r','').strip()
    cues=[]
    for block in re.split(r'\n\s*\n',text):
        lines=block.splitlines()
        if len(lines)<3 or not lines[0].strip().isdigit(): raise ValueError('字幕必须是 UTF-8 SRT，含编号、时间、文字：'+str(path))
        def stamp(s):
            m=re.fullmatch(r'(\d+):(\d\d):(\d\d)[,.](\d{3})',s.strip())
            if not m: raise ValueError('字幕时间格式错误：'+s)
            h,mn,sec,ms=map(int,m.groups())
            if mn>=60 or sec>=60: raise ValueError('字幕时间无效')
            return h*3600+mn*60+sec+ms/1000
        pair=lines[1].split('-->')
        if len(pair)!=2: raise ValueError('字幕缺少 -->')
        a,b=map(stamp,pair)
        if a>=b or (cues and a<cues[-1][2]-.001): raise ValueError('字幕时间重叠或倒序，请先校正')
        cues.append((int(lines[0]),a,b,'\n'.join(lines[2:])))
    if not cues or len({x[0] for x in cues})!=len(cues): raise ValueError('字幕为空或编号重复')
    return cues

def stamp(t,ass=False):
    n=round(max(t,0)*(100 if ass else 1000)); unit=100 if ass else 1000
    sec,part=divmod(n,unit); mins,sec=divmod(sec,60); h,mins=divmod(mins,60)
    return f'{h}:{mins:02}:{sec:02}.{part:02}' if ass else f'{h:02}:{mins:02}:{sec:02},{part:03}'

def write_subs(cues,folder,w,h,font,size):
    (folder/'subtitles.srt').write_text('\n\n'.join(f'{i}\n{stamp(a)} --> {stamp(b)}\n{txt}' for i,a,b,txt in cues)+'\n',encoding='utf-8-sig')
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00202020,&H00000000,0,0,0,0,100,100,0,0,1,{max(1,h/480)},0,2,{round(w*.08)},{round(w*.13)},{round(h*.12)},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    # Strip SRT styling; never allow ASS code from subtitle text.
    for _,a,b,txt in cues:
        txt=re.sub(r'<[^>]*>','',txt).replace('\\','／').replace('{','｛').replace('}','｝').replace('\n',r'\N')
        header+=f'Dialogue: 0,{stamp(a,True)},{stamp(b,True)},Default,,0,0,0,,{txt}\n'
    (folder/'subtitles.ass').write_text(header,encoding='utf-8-sig')

