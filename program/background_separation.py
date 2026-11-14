"""Real source separation preview; no denoiser or mute fallback."""
import importlib.util,json,sys
from pathlib import Path
from media import run,executable,probe

def separate(source,folder,cancel,progress=lambda s:None,model='htdemucs_ft',limit=None,start=0):
    source=Path(source);folder=Path(folder)
    if not source.is_file():raise ValueError('请选择含原音乐的片头视频。')
    if importlib.util.find_spec('demucs') is None:
        raise RuntimeError('此独立CPU环境尚未安装Demucs。请先关闭软件，运行 INSTALL_BACKGROUND_MODEL.bat，再做20秒试听。原片未改变；不会用普通降噪代替。')
    if model not in ('htdemucs_ft','htdemucs'):raise ValueError('未验证的分离模型名称。')
    duration=float(probe(source,cancel)['format']['duration'])-start
    if limit is not None:duration=min(limit,duration)
    if duration<=0:raise ValueError('试听起点超出原片头。')
    wav=folder/('original_20s.wav' if limit else 'original_full.wav')
    run([executable('ffmpeg'),'-nostdin','-y','-v','error','-i',str(source),'-ss',str(start),'-t',str(duration),'-ar','44100','-ac','2',str(wav)],cancel)
    progress('实际模型分离背景声；CPU处理可能较慢，可停止。输出仍须试听检查中文残留。')
    run([sys.executable,'-m','demucs','-n',model,'--two-stems','vocals','-d','cpu','--shifts','1','--segment','7','--int24','-o',str(folder/'separated'),str(wav)],cancel)
    result=folder/'separated'/model/wav.stem/'no_vocals.wav'
    if not result.is_file():raise RuntimeError('模型没有生成背景声轨，未报告分离成功。')
    (folder/'separation_report.json').write_text(json.dumps(dict(model=model,duration=duration,source=str(source),output=str(result),quality_approved=False,notes='实际伴奏分离结果；不保证中文或混响完全消失，需用户试听。'),ensure_ascii=False,indent=2),encoding='utf8')
    return str(result)

def preview(source,folder,cancel,progress=lambda s:None,model='htdemucs_ft',start=0):
    return separate(source,folder,cancel,progress,model,limit=20,start=start)
