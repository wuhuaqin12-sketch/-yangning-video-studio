"""Language-independent typography, colour rules and safe ASS text generation."""
import json
import math
import re
import unicodedata
from pathlib import Path

DEFAULTS = dict(title='', font='Noto Serif CJK JP', title_font='Yuji Boku',
    subtitle_color='#FFFFFF', title_color='#34221B', outline_color='#202020',
    subtitle_outline=3, title_outline=0, subtitle_x=50, subtitle_y=76,
    subtitle_width=92, subtitle_height=32, font_percent=4.5,
    subtitle_font_size=70, title_font_size=230, title_x=50, title_y=25,
    title_width=94, title_size=12, video_width=100, video_height=76,
    auto_fit=True, keywords='', keyword_color='#E53935',
    keyword_ignore_case=True, keyword_whole_words=False)

LIMITS = {'subtitle_x':(0,100), 'subtitle_y':(0,100),
    'subtitle_width':(5,100), 'subtitle_height':(3,80), 'font_percent':(1,25),
    'title_x':(0,100), 'title_y':(0,100), 'title_width':(5,100),
    'title_size':(1,25), 'video_width':(20,100), 'video_height':(20,100),
    'subtitle_outline':(0,12), 'title_outline':(0,12)}

def boolean(value):
    if isinstance(value,bool):return value
    if value in (1,'1','true','True'):return True
    if value in (0,'0','false','False'):return False
    raise ValueError('开关值无效，请重新选择。')

def colour(value):
    if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value.strip()):
        raise ValueError('颜色请用 #RRGGBB 格式，例如 #E53935。')
    return value.strip().upper()

def ass_colour(value, inline=False):
    rgb=colour(value)[1:];bgr=rgb[4:6]+rgb[2:4]+rgb[0:2]
    return '&H'+bgr+'&' if inline else '&H00'+bgr

def clean(text):
    # No imported SRT styling can become ASS instructions. Keep scripts and marks.
    text=re.sub(r'<[^>]*>', '',str(text)).replace('\\','／').replace('{','｛').replace('}','｝')
    return ''.join(c for c in text if c in '\n\t' or unicodedata.category(c)!='Cc')

def parse_keywords(text, default_colour):
    if not isinstance(text,str):raise ValueError('重点词列表须为文字。')
    rules={}
    for line in text.splitlines():
        line=line.strip()
        if not line:continue
        if '=' in line:
            word,_,value=line.rpartition('=');value=colour(value)
        else:word,value=line,colour(default_colour)
        word=clean(word.strip())
        if not word:raise ValueError('重点词不能为空。')
        if len(word)>300:raise ValueError('单个重点词过长。')
        rules[word]=value
    if len(rules)>200:raise ValueError('重点词最多200条，请减少条数。')
    return sorted(rules.items(),key=lambda pair:-len(pair[0]))

def normalize_style(values):
    opts={**DEFAULTS,**{k:v for k,v in values.items() if k in DEFAULTS}}
    for key,(lo,hi) in LIMITS.items():
        try:n=float(opts[key])
        except (TypeError,ValueError):raise ValueError('排版数值无效：'+key)
        if not math.isfinite(n) or not lo<=n<=hi:raise ValueError(f'{key} 应为 {lo:g}–{hi:g}。')
        opts[key]=n
    for key in ('subtitle_font_size','title_font_size'):
        if opts[key] in ('',None):opts[key]='';continue
        try:n=float(opts[key])
        except (TypeError,ValueError):raise ValueError('字号须为数字。')
        if not math.isfinite(n) or not 10<=n<=480:raise ValueError('字号须为10–480像素。')
        opts[key]=n
    for key in ('subtitle_color','title_color','outline_color','keyword_color'):opts[key]=colour(opts[key])
    for key in ('font','title_font'):
        if not isinstance(opts[key],str) or not opts[key].strip() or any(c in opts[key] for c in ',\r\n\t'):
            raise ValueError('请选择有效字体，字体名不能含逗号或换行。')
        opts[key]=opts[key].strip()
    for key in ('auto_fit','keyword_ignore_case','keyword_whole_words'):opts[key]=boolean(opts[key])
    if not isinstance(opts['title'],str) or len(opts['title'])>2000:raise ValueError('标题过长或格式无效。')
    parse_keywords(opts['keywords'],opts['keyword_color'])
    return opts

def units(text):
    return sum(0 if unicodedata.category(c).startswith('M') or c in '\u200d\u200c\ufe0e\ufe0f' else
               1 if unicodedata.east_asian_width(c) in 'WF' else .65 for c in text)

def clusters(text):
    """Keep combining marks, variation selectors, viramas and ZWJ sequences together."""
    result=[]
    for i,char in enumerate(text):
        last=result[-1][1][-1] if result else ''
        attach=(unicodedata.category(char).startswith('M') or char in '\u200d\u200c\ufe0e\ufe0f' or
                last=='\u200d' or 'VIRAMA' in (unicodedata.name(last,'') if last else '') or 'HALANT' in (unicodedata.name(last,'') if last else ''))
        if result and attach:result[-1]=(result[-1][0],result[-1][1]+char)
        else:result.append((i,char))
    return result

def line_parts(text, columns):
    """Wrap before colouring, retaining source offsets for matches crossing new wraps."""
    result=[];offset=0
    for paragraph in text.split('\n'):
        line=[];width=0
        for token in re.finditer(r'\s+|\S+',paragraph):
            raw=token.group();atoms=[(offset+token.start()+i,c) for i,c in clusters(raw)]
            tw=units(raw)
            if line and width+tw>columns and not raw.isspace():
                while line and line[-1][1].isspace():line.pop()
                result.append(line);line=[];width=0
            if not line and raw.isspace():continue
            for i,c in atoms:
                cw=units(c)
                if line and width+cw>columns:
                    while line and line[-1][1].isspace():line.pop()
                    result.append(line);line=[];width=0
                if not line and c.isspace():continue
                line.append((i,c));width+=cw
        while line and line[-1][1].isspace():line.pop()
        result.append(line);offset+=len(paragraph)+1
    return result

def wrap(text, columns):return [''.join(c for _,c in row) for row in line_parts(clean(text),columns)]

def fit_lines(text,size,width,height,auto_fit=True,leading=1.4):
    initial=max(10,round(size));size=initial
    while size>=10:
        lines=line_parts(text,max(1,(width-12)/(size*1.1)))
        if len(lines)*size*leading<=height and all(units(''.join(c for _,c in row))*size*1.1<=width-11 for row in lines):
            return size,lines
        if not auto_fit:break
        size-=1
    raise ValueError('所选字号放不下文字。请扩大文字区域、拆分长字幕，或统一调整字号。')

def matched_colours(text, opts):
    rules=parse_keywords(opts['keywords'],opts['keyword_color'])
    if not rules:return {}
    # Build one escaped alternation: leftmost, longest match; no user regex/code.
    patterns=[]
    for word,_ in rules:
        p=re.escape(word)
        if opts['keyword_whole_words'] and word[0].isascii() and word[0].isalnum():p=r'(?<!\w)'+p
        if opts['keyword_whole_words'] and word[-1].isascii() and word[-1].isalnum():p+=r'(?!\w)'
        patterns.append('('+p+')')
    pattern=re.compile('|'.join(patterns),re.IGNORECASE if opts['keyword_ignore_case'] else 0)
    colours={}
    for match in pattern.finditer(text):
        value=rules[match.lastindex-1][1]
        for i in range(match.start(),match.end()):colours[i]=value
    return colours

def styled_lines(text,lines,opts,highlight=True):
    colours=matched_colours(text,opts) if highlight else {};base=opts['subtitle_color']
    result=[]
    for row in lines:
        out='';active=base
        for i,char in row:
            wanted=colours.get(i,base)
            if wanted!=active:out+='{\\1c'+ass_colour(wanted,True)+'}';active=wanted
            out+=char
        if active!=base:out+='{\\1c'+ass_colour(base,True)+'}'
        result.append(out)
    return r'\N'.join(result)

def fit_text(text,size,width,height):
    opts=normalize_style({});text=clean(text);size,lines=fit_lines(text,size,width,height)
    return size,styled_lines(text,lines,opts,highlight=False)

def save_preset(path,values):
    opts=normalize_style(values)
    Path(path).write_text(json.dumps({'format':'YangNingPublishStyle','version':1,'settings':opts},ensure_ascii=False,indent=2),encoding='utf8')

def load_preset(path):
    path=Path(path)
    if path.stat().st_size>1024*1024:raise ValueError('样式文件过大。')
    payload=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(payload,dict) or payload.get('format')!='YangNingPublishStyle' or payload.get('version')!=1 or not isinstance(payload.get('settings'),dict):
        raise ValueError('这不是本工具的样式文件。')
    return normalize_style(payload['settings'])
