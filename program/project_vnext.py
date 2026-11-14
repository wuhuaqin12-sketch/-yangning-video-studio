"""Versioned project settings, independent layouts and content-addressed cache keys."""
import hashlib,json,math,os,re,uuid
from pathlib import Path
from desktop_update import atomic_json

SCHEMA=1
DEFAULTS=dict(background_audio='',background_audio_offset=0,output_mode='auto',intro_enabled=False,intro_video='',intro_mode='original',
    intro_audio='',intro_srt='',intro_target_srt='',intro_clean_audio=False,
    intro_separation_approved='',intro_separation_model='htdemucs_ft',intro_music_gain=1.0,
    outro_enabled=False,outro_video='',cover='',cover_landscape='',cover_portrait='',
    cover_seconds=3,cover_transition='cut',cover_fit='ask',background='',
    combined=False,combined_intro_end=0,combined_outro_start=0,combined_audio_split=0,
    preview_start=0,preview_seconds=15,layouts={
      'landscape':dict(remove_chinese=True,repair_method='glyph',repair_roi='',repair_approved='',repair_temporal=False,subtitle_offset_y=0,clean_video='',title_y='',title_font_size='',subtitle_font_size='84',style={}),
      'portrait':dict(remove_chinese=False,repair_method='glyph',repair_roi='',repair_approved='',repair_temporal=False,subtitle_offset_y=0,clean_video='',title_y='',title_font_size='',subtitle_font_size='',style={})})
DEFAULTS.update(opening_title_enabled=False,opening_title_original='金刚经讲义',opening_title_text='',opening_title_start=0,opening_title_end=15,opening_title_x=50,opening_title_y=70,opening_title_size=64,
    disclaimer_enabled=False,disclaimer_image='',disclaimer_seconds=5,disclaimer_mode='append')
DEFAULTS.update(opening_topic_enabled=False,opening_topic_original='经题',opening_topic_text='',opening_topic_start=75,opening_topic_end=87,opening_topic_x=50,opening_topic_y=70,opening_topic_size=64)
for prefix in ('opening_title','opening_topic'):
    DEFAULTS.update({prefix+'_font':'Yuji Boku',prefix+'_color':'#FFFFFF' if prefix=='opening_title' else '#101010',prefix+'_orientation':'horizontal',prefix+'_auto_style':True,prefix+'_match_size':False,prefix+'_reference_height':0,prefix+'_reference_advance':0})

def defaults():return json.loads(json.dumps(DEFAULTS))

def normalize(value):
    result=defaults();result.update({k:v for k,v in (value or {}).items() if k!='layouts' and k in result})
    for mode in ('landscape','portrait'):
        saved=(value or {}).get('layouts',{}).get(mode,{})
        result['layouts'][mode].update(saved)
        # Preserve explicit sizes; obsolete rectangle approvals must be reviewed again.
        if saved and saved.get('repair_method')!='glyph':result['layouts'][mode]['repair_approved']=''
        result['layouts'][mode]['repair_method']='glyph'
        result['layouts'][mode]['repair_temporal']=False
    if result['output_mode'] not in ('auto','landscape','portrait','both'):raise ValueError('输出比例选项无效。')
    if result['intro_mode'] not in ('original','music_voice','external_music'):raise ValueError('片头声音选项无效。')
    result['cover_seconds']=int(result['cover_seconds'])
    if result['cover_seconds'] not in (2,3,5):raise ValueError('封面时长请选择2、3或5秒。')
    if result['cover_transition'] not in ('cut','dissolve'):raise ValueError('封面转场无效。')
    if result['cover_fit'] not in ('ask','contain','crop'):raise ValueError('封面适配方式无效。')
    result['intro_music_gain']=float(result['intro_music_gain'])
    if not math.isfinite(result['intro_music_gain']) or not 0<=result['intro_music_gain']<=2:raise ValueError('片头音乐音量倍数须在0–2之间。')
    for key in ('background_audio_offset','combined_intro_end','combined_outro_start','combined_audio_split','preview_start','preview_seconds'):
        number=float(result[key])
        if not math.isfinite(number) or number<0:raise ValueError('时间必须是非负秒数：'+key)
        result[key]=number
    if not 1<=result['preview_seconds']<=60:raise ValueError('预览长度须在1–60秒之间。')
    for key in (*[prefix+'_'+suffix for prefix in ('opening_title','opening_topic') for suffix in ('start','end','x','y','size','reference_height','reference_advance')],'disclaimer_seconds'):
        result[key]=float(result[key])
        if not math.isfinite(result[key]):raise ValueError('数值无效：'+key)
    for prefix in ('opening_title','opening_topic'):
        if not 0<=result[prefix+'_start']<result[prefix+'_end']:raise ValueError('片头译名结束秒必须大于开始秒。')
        if not 0<result[prefix+'_x']<100 or not 0<result[prefix+'_y']<100:raise ValueError('片头译名位置须在画面0–100%内部。')
        if not 20<=result[prefix+'_size']<=480:raise ValueError('片头译名字号须在20–480之间。')
        from publish_style import colour,boolean
        result[prefix+'_color']=colour(result[prefix+'_color'])
        if not isinstance(result[prefix+'_font'],str) or not result[prefix+'_font'].strip() or any(c in result[prefix+'_font'] for c in ',\r\n\t'):raise ValueError('请选择有效字体。')
        if result[prefix+'_orientation'] not in ('horizontal','vertical'):raise ValueError('译名横竖排选项无效。')
        if not 0<=result[prefix+'_reference_height']<=50:raise ValueError('原字参考高度无效，请重新定位。')
        if not 0<=result[prefix+'_reference_advance']<=100:raise ValueError('原字参考间距无效，请重新定位。')
        for suffix in ('auto_style','match_size'):result[prefix+'_'+suffix]=boolean(result[prefix+'_'+suffix])
    if not 2<=result['disclaimer_seconds']<=30:raise ValueError('免责声明显示秒数须在2–30之间。')
    if result['disclaimer_mode'] not in ('append','overlay'):raise ValueError('免责声明方式无效。')
    return result

def media_paths(job):
    result={k:job.get(k) for k in ('video','audio','source_srt','target_srt') if job.get(k)}
    p=normalize(job.get('sequence'))
    for k in ('intro_video','intro_audio','intro_srt','intro_target_srt'):
        if p['intro_enabled'] and p.get(k) and (k=='intro_video' or p['intro_mode']=='music_voice'):result[k]=p[k]
    if p['outro_enabled'] and p['outro_video']:result['outro_video']=p['outro_video']
    for k in ('cover','cover_landscape','cover_portrait','background','background_audio'):
        if p[k]:result[k]=p[k]
    if p['disclaimer_enabled'] and p['disclaimer_image']:result['disclaimer_image']=p['disclaimer_image']
    for mode in ('landscape','portrait'):
        if p['layouts'][mode].get('clean_video'):result[mode+'_clean_video']=p['layouts'][mode]['clean_video']
    return result

def save_project(path,job):
    atomic_json(path,dict(schema=SCHEMA,job=job))

def load_project(path):
    data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if data.get('schema')!=SCHEMA or not isinstance(data.get('job'),dict):raise ValueError('项目格式或版本无效。')
    job=data['job'];job['sequence']=normalize(job.get('sequence'))
    base=Path(path).resolve().parent
    def absolute(value):
        if not value:return value
        if Path(value).is_absolute() or re.match(r'^[A-Za-z]:[\\/]',str(value)) or str(value).startswith('\\\\'):return str(value)
        return str((base/value).resolve())
    for key in ('video','audio','source_srt','target_srt','audio_reference_srt','output'):
        if job.get(key):job[key]=absolute(job[key])
    for key in ('intro_video','intro_audio','intro_srt','intro_target_srt','outro_video','cover','cover_landscape','cover_portrait','background','background_audio','disclaimer_image'):
        if job['sequence'].get(key):job['sequence'][key]=absolute(job['sequence'][key])
    for layout in job['sequence']['layouts'].values():
        if layout.get('clean_video'):layout['clean_video']=absolute(layout['clean_video'])
    if (job.get('publish_settings') or {}).get('background'):job['publish_settings']['background']=absolute(job['publish_settings']['background'])
    missing={k:v for k,v in media_paths(job).items() if not Path(v).is_file()}
    return job,missing

def file_digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()

def processing_key(job):
    # Layout, covers and burn-in are deliberately excluded. Use full file hashes,
    # not only beginning/end fingerprints, so interior changes invalidate cache.
    value={k:job.get(k) for k in ('language','alignment','speed','trim','audio_profile','audio_separate','_pause_override')}
    value['cache_schema']=1
    from engine import VERSION
    value['processing_version']=VERSION
    value['files']={k:file_digest(job[k]) for k in ('video','audio','source_srt','target_srt','audio_reference_srt') if job.get(k)}
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

def preview_key(job):
    settings=normalize(job.get('sequence'))
    settings.pop('preview_start',None);settings.pop('preview_seconds',None)
    value={k:job.get(k) for k in ('language','alignment','speed','trim','audio_profile','audio_separate','burn','publish_settings','_pause_override')}
    value['sequence']=settings
    value['files']={k:file_digest(v) for k,v in media_paths(job).items()}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def unique_output(folder,name,language,mode):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    safe=lambda s:re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',str(s)).strip(' .')[:100] or 'video'
    label={'ja':'日语','en':'英语','fr':'法语','de':'德语','id':'印尼语','zh':'中文','ko':'韩语','es':'西班牙语','pt':'葡萄牙语','it':'意大利语'}.get(language,language)
    stem=f'{safe(name)}_{safe(label)}_'+('横版_16x9' if mode=='landscape' else '竖版_9x16')
    for i in range(10000):
        p=folder/(stem+(f'_{i}' if i else '')+'.mp4')
        # Keep orphaned subtitle files too; never silently replace an old SRT.
        if p.with_suffix('.srt').exists():continue
        # Reserve the filename atomically, avoiding concurrent export collisions.
        try:
            fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd);return p
        except FileExistsError:continue
    raise ValueError('同名文件过多，请换项目名称。')
