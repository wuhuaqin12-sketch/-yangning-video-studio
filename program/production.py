"""Finish the selected audio-review project without losing confirmed edits."""
import json,shutil,tempfile
from pathlib import Path

def same_material(folder,values):
    folder=Path(folder)
    def path(value):return Path(value).resolve() if value else None
    if (folder/'clean_project.json').is_file():
        m=json.loads((folder/'clean_project.json').read_text(encoding='utf8'));video,audio=m['video'],m['audio']
    elif (folder/'analysis.json').is_file():
        m=json.loads((folder/'analysis.json').read_text(encoding='utf8'));video,audio=m['job']['video'],m['job']['audio']
    else:return False
    return path(video)==path(values.get('video')) and path(audio)==path(values.get('audio') or values.get('video'))

def finish(folder,values,style,auto_cut,cancel,progress=lambda s:None):
    folder=Path(folder)
    if (folder/'clean_project.json').is_file():
        import clean_project as cp
        from auto_silence import propose
        m=cp.load(folder)
        mode=m.get('denoise',{}).get('mode','original_audio')
        expected=values.get('audio_profile')
        if expected in (None,'off'):expected='separation_only' if values.get('audio_separate') else 'original_audio'
        if mode!=expected or bool(m.get('separation'))!=bool(values.get('audio_separate')):
            raise ValueError('声音设置已改变，请先在步骤2重新处理；原有工程与修改保留。')
        def path(v):return str(Path(v).resolve()) if v else ''
        if path(values.get('source_srt'))!=path(m['sources'].get('srt',[''])[0]) or path(values.get('audio_reference_srt'))!=path(m.get('denoise',{}).get('reference_path','')):
            raise ValueError('字幕选择已改变，请先重新准备试听工程；原有静音修改保留。')
        m['auto_edits']=propose(folder/'original.wav',m['cues']) if auto_cut else []
        m['style']=style or None;cp.save(folder/'clean_project.json',m)
        progress('沿用已确认的静音和修改，应用停顿及排版设置…')
        output=Path(cp.export(folder,cancel,progress))
    else:
        import engine
        from audio_edit import propose,export_plan
        m=json.loads((folder/'analysis.json').read_text(encoding='utf8'))
        keys=('audio_profile','audio_separate','source_srt','target_srt','audio_reference_srt','language')
        for key in keys:
            if (m['job'].get(key) or '')!=(values.get(key) or ''):
                # Empty target_srt is normalized to source_srt when analysis starts.
                if key=='target_srt' and not values.get(key) and m['job'].get(key)==values.get('source_srt'):continue
                raise ValueError('素材或声音选项已改变，请先重新分析；原有工程保留。')
        if bool(m['job'].get('trim',True))!=bool(auto_cut):
            words=json.loads((folder/'words.json').read_text(encoding='utf8'))['words'] if (folder/'words.json').is_file() else None
            events=propose(m['target'],m['silences'],m['audio_duration'],m['rate'],m['channels'],folder/'original.f32',bool(auto_cut),words,m['job'].get('language'))
            export_plan(events,folder/'pause_plan.csv');m['job']['trim']=bool(auto_cut)
        m['publish_settings']=style or None;engine.save_json(folder/'analysis.json',m)
        engine.render(folder,cancel,progress);output=folder/'video.mp4'
    destination=Path(values['output']).resolve()
    if output.parent.resolve().parent!=destination:
        destination.mkdir(parents=True,exist_ok=True)
        result=Path(tempfile.mkdtemp(prefix='成片_',dir=destination))
        for name in ('video.mp4','subtitles.srt','cover.png','声音处理明细.txt','声音处理明细.csv','声音处理明细.json','声音处理报告.json','export_report.json','report.json'):
            source=output.parent/name
            if source.is_file():shutil.copyfile(source,result/name)
        output=result/'video.mp4'
    return str(output)
