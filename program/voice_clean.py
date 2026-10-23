"""Optional local audio treatment; sample-count invariant, never edit source media."""
import os,sys,json,shutil,venv,tempfile,hashlib,math
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from media import executable,run,Cancelled

PROFILE='v11'
DEEP_PROFILE='v11_deep'
MODEL_DIGEST='ae3f7411e1e6a884f839a4a145c394408398f09854dbc1216ee02faafc98a17b'
def enabled(job):return job.get('audio_profile') in (PROFILE,DEEP_PROFILE) or job.get('audio_separate') is True

def isolate(source,destination,workspace,cancel,progress):
    if not (3,10)<=sys.version_info[:2]<=(3,12):
        raise ValueError('人声分离需要64位 Python 3.10–3.12；降噪本身可继续使用。')
    from desktop_update import install_root
    root=install_root()/'voice_separation_runtime';python=root/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    marker=root/'demucs_4_0_1.ok'
    if not marker.exists():
        progress('首次准备人声分离环境，需要联网及较大下载；可点击停止。')
        if not python.exists():venv.EnvBuilder(with_pip=True).create(root)
        # Keep optional model dependencies out of the main application runtime.
        run([str(python),'-m','pip','install','torch==2.5.1','torchaudio==2.5.1','--index-url','https://download.pytorch.org/whl/cpu'],cancel)
        run([str(python),'-m','pip','install','numpy<2','demucs==4.0.1','soundfile==0.13.1'],cancel)
        marker.write_text('demucs4 torch2.5.1',encoding='ascii')
    progress('本地分离人声与背景音乐；首次运行需要下载模型，处理可能较慢。')
    output=Path(workspace)/'separation'
    run([str(python),'-m','demucs','--two-stems','vocals','-n','htdemucs','-d','cpu','--shifts','0','--float32','-o',str(output),str(source)],cancel)
    vocals=output/'htdemucs'/Path(source).stem/'vocals.wav'
    if not vocals.is_file():raise RuntimeError('人声分离未生成输出；未回退冒充成功。')
    r,x=wavfile.read(source);channels=1 if x.ndim==1 else x.shape[1]
    run([executable('ffmpeg'),'-v','error','-y','-i',str(vocals),'-ar',str(r),'-ac',str(channels),'-c:a','pcm_f32le',str(destination)],cancel)
    rr,y=wavfile.read(destination)
    if abs(len(y)-len(x))>r*.03:raise RuntimeError('人声分离输出时长改变，已停止。')
    if len(y)<len(x):y=np.pad(y,[(0,len(x)-len(y))]+([(0,0)] if y.ndim==2 else []))
    wavfile.write(destination,r,y[:len(x)].astype('float32'))
    return {'model':'htdemucs','engine':'demucs 4.0.1','background':str(output/'htdemucs'/Path(source).stem/'no_vocals.wav')}

def process_wav(source,destination,job,cancel,progress=lambda s:None):
    source,destination=Path(source),Path(destination)
    if source.resolve()==destination.resolve():raise ValueError('必须保留原声，不能覆盖源文件。')
    if cancel.is_set():raise Cancelled()
    if not enabled(job):
        shutil.copyfile(source,destination)
        return dict(enabled=False,mode='original_audio',separation=None)
    rate,x=wavfile.read(source)
    if x.dtype.kind!='f':raise ValueError('声音处理需要解码后的浮点PCM。')
    separation=None;input_file=source
    if job.get('audio_separate'):
        input_file=destination.with_name('vocals.wav')
        separation=isolate(source,input_file,destination.parent,cancel,progress)
    deep=job.get('audio_profile')==DEEP_PROFILE
    denoise=job.get('audio_profile') in (PROFILE,DEEP_PROFILE)
    progress('整段温和降噪：低频底噪、持续沙沙声、短促点击声；保留语音与时长。' if denoise else '仅分离人声，保留时间轴。')
    # afftdn's overlap buffer delays content by two 12.5ms hops.
    # Pad the tail before filtering, then remove that exact delay so word
    # onsets and final syllables stay on the original sample timeline.
    latency=2*(rate//80)
    filters=f'apad=pad_len={latency+rate//10},highpass=f=60,adeclick=t=4,afftdn=nr=12:nf=-50:tn=1:gs=8,atrim=start_sample={latency}:end_sample={latency+len(x)},asetpts=PTS-STARTPTS' 
    model=None
    if deep:
        model=Path(__file__).resolve().parent/'models/bd.rnnn'
        if not model.is_file() or hashlib.sha256(model.read_bytes()).hexdigest()!=MODEL_DIGEST:
            raise RuntimeError('V11 加强降噪模型缺失或校验失败，请安装完整更新包；未回退冒充成功。')
        progress('V11 加强降噪；句前多余颤音仍需字幕对照及试听后确认静音。')
        latency=480
        end=480+math.ceil(len(x)*48000/rate)
        filters=f'aresample=48000,highpass=f=75,adeclick=t=3,apad=pad_len=5280,arnndn=m=bd.rnnn:mix=1,atrim=start_sample=480:end_sample={end},asetpts=PTS-STARTPTS,aresample={rate},apad=pad_len=2,atrim=end_sample={len(x)}'
    if not denoise:filters='anull'
    partial=destination.with_name(destination.stem+'.partial.wav')
    try:
        # A relative ASCII model basename avoids Windows drive/quote escaping
        # inside FFmpeg's filter parser, even for Chinese installation paths.
        with tempfile.TemporaryDirectory(prefix='v11_filter_') as work:
            if model:shutil.copyfile(model,Path(work)/'bd.rnnn')
            run([executable('ffmpeg'),'-v','error','-y','-i',str(input_file.resolve()),'-af',filters,'-ar',str(rate),'-c:a','pcm_f32le',str(partial.resolve())],cancel,cwd=work)
        r,y=wavfile.read(partial)
        if r!=rate or y.shape!=x.shape:raise RuntimeError('降噪改变采样数或声道，已停止以保护同步。')
        if not np.isfinite(y).all():raise RuntimeError('声音处理结果包含无效采样。')
        peak=float(np.max(np.abs(y))) if y.size else 0
        gain=min(1.,.98/peak) if peak else 1.
        if gain<1:wavfile.write(partial,r,(y*gain).astype('float32'))
        partial.replace(destination)
        report=dict(enabled=True,mode=job.get('audio_profile') if denoise else 'separation_only',denoise_enabled=denoise,filters=filters,rate=rate,samples=len(y),compensated_latency_samples=latency if denoise else 0,latency_sample_rate=48000 if deep else rate,manual_phrase_review_required=True,semantic_noise_removal=False,channels=1 if y.ndim==1 else y.shape[1],separation=separation,peak_gain=gain,
                    note='降噪不能保证消除全部杂音；保留原声供A/B试听。杂声和人声重叠时可能残留，不自动删词。')
        (destination.parent/'声音处理报告.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        return report
    finally:partial.unlink(missing_ok=True)
