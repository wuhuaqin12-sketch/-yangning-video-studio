"""Versioned project settings, independent layouts and content-addressed cache keys."""
import hashlib,json,math,os,re,uuid
from pathlib import Path
from desktop_update import atomic_json

SCHEMA=1
DEFAULTS=dict(output_mode='auto',intro_enabled=False,intro_video='',intro_mode='original',
    intro_audio='',intro_srt='',intro_target_srt='',intro_clean_audio=False,
    intro_separation_approved='',intro_separation_model='htdemucs_ft',
    outro_enabled=False,outro_video='',cover='',cover_landscape='',cover_portrait='',
    cover_seconds=3,cover_transition='cut',cover_fit='ask',background='',
    combined=False,combined_intro_end=0,combined_outro_start=0,combined_audio_split=0,
    preview_start=0,preview_seconds=15,layouts={
      'landscape':dict(remove_chinese=True,repair_roi='',repair_approved='',repair_temporal=True,subtitle_offset_y=0,clean_video='',title_y='',title_font_size='',subtitle_font_size='',style={}),
      'portrait':dict(remove_chinese=False,repair_roi='',repair_approved='',repair_temporal=True,subtitle_offset_y=0,clean_video='',title_y='',title_font_size='',subtitle_font_size='',style={})})

def defaults():return json.loads(json.dumps(DEFAULTS))

def normalize(value):
    result=defaults();result.update({k:v for k,v in (value or {}).items() if k!='layouts' and k in result})
    for mode in ('landscape','portrait'):result['layouts'][mode].update((value or {}).get('layouts',{}).get(mode,{}))
    if result['output_mode'] not in ('auto','landscape','portrait','both'):raise ValueError('输出比例选项无效。')
    if result['intro_mode'] not in ('original','music_voice'):raise ValueError('片头声音选项无效。')
    result['cover_seconds']=int(result['cover_seconds'])
    if result['cover_seconds'] not in (2,3,5):raise ValueError('封面时长请选择2、3或5秒。')
    if result['cover_transition'] not in ('cut','dissolve'):raise ValueError('封面转场无效。')
    if result['cover_fit'] not in ('ask','contain','crop'):raise ValueError('封面适配方式无效。')
    for key in ('combined_intro_end','combined_outro_start','combined_audio_split','preview_start','preview_seconds'):
        number=float(result[key])
        if not math.isfinite(number) or number<0:raise ValueError('时间必须是非负秒数：'+key)
        result[key]=number
    if not 1<=result['preview_seconds']<=60:raise ValueError('预览长度须在1–60秒之间。')
    return result

def media_paths(job):
    result={k:job.get(k) for k in ('video','audio','source_srt','target_srt') if job.get(k)}
    p=normalize(job.get('sequence'))
    for k in ('intro_video','intro_audio','intro_srt','intro_target_srt'):
        if p['intro_enabled'] and p.get(k):result[k]=p[k]
    if p['outro_enabled'] and p['outro_video']:result['outro_video']=p['outro_video']
    for k in ('cover','cover_landscape','cover_portrait','background'):
        if p[k]:result[k]=p[k]
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
    for key in ('intro_video','intro_audio','intro_srt','intro_target_srt','outro_video','cover','cover_landscape','cover_portrait','background'):
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
        # Reserve the filename atomically, avoiding concurrent export collisions.
        try:
            fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd);return p
        except FileExistsError:continue
    raise ValueError('同名文件过多，请换项目名称。')
