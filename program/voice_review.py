"""Streaming waveform checks only; never certify identity, wording or pronunciation."""
import hashlib
import json
import math
import wave
from pathlib import Path
import numpy as np


def file_sha256(path):
    digest=hashlib.sha256()
    with open(path,"rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""): digest.update(block)
    return digest.hexdigest()


def describe_review(report):
    flags=report.get("flags",[])
    return (f"时长：{report['seconds']:.2f}秒\n声道：{report['channels']}\n"
            f"平均电平：{report['rms_dbfs']:.1f} dBFS\n最长内部低能量间隔：{report['longest_internal_low_energy_seconds']:.2f}秒\n\n"
            +("复听提示：\n"+"\n".join(flags) if flags else "未发现明显的音量或静音异常。")
            +"\n\n此检查只分析波形，未验证音色、全文完整性、术语读音或语气；不会裁剪停顿。")


def review_wav(path):
    peak, energy, samples, clipped = 0.0, 0.0, 0, 0
    seen_voice, pending_pause, longest_pause = False, 0.0, 0.0
    with wave.open(str(path),"rb") as source:
        channels,rate=source.getnchannels(),source.getframerate()
        if source.getsampwidth()!=2 or channels not in (1,2):
            raise ValueError("波形检查需要单/双声道PCM16 WAV。")
        duration=source.getnframes()/rate
        frames=max(1,round(rate*.02))
        while True:
            data=source.readframes(frames)
            if not data: break
            values=np.frombuffer(data,dtype="<i2").astype(np.float64)/32768
            count=len(values)
            peak=max(peak,float(np.max(np.abs(values))))
            energy+=float(np.sum(values*values));samples+=count
            clipped+=int(np.count_nonzero(np.abs(values)>=32760/32768))
            rms=math.sqrt(float(np.mean(values*values)))
            if rms>=.001:
                if seen_voice: longest_pause=max(longest_pause,pending_pause)
                seen_voice=True;pending_pause=0.0
            elif seen_voice:
                pending_pause+=count/channels/rate
    rms=math.sqrt(energy/samples) if samples else 0.0
    flags=[]
    if not samples or peak<.0001: flags.append("无声或几乎无声，请复听")
    elif rms<.01: flags.append("整体音量较低，请复听")
    if clipped: flags.append("检测到接近满幅的样本，请复听是否削波")
    if longest_pause>3: flags.append("内部有超过3秒的低能量间隔，请复听；未裁剪")
    return {"method":"waveform_only","seconds":round(duration,4),"channels":channels,
            "peak":round(peak,6),"rms_dbfs":round(20*math.log10(max(rms,1e-12)),2),
            "near_fullscale_samples":clipped,"longest_internal_low_energy_seconds":round(longest_pause,3),
            "flags":flags,"silence_trimmed":False,"review_required":["音色相似度","全文完整性","术语读音","语气与接缝"],
            "transcript_or_voice_verified":False}


def write_review(audio, destination):
    report=review_wav(audio)
    path=Path(destination)
    partial=path.with_suffix(path.suffix+".tmp")
    partial.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    partial.replace(path)
    return report
