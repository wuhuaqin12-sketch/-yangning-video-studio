"""Text auditions and hash-bound generated-unit selection; no ASR claims."""
import json
import math
import wave
from pathlib import Path
from voice_review import file_sha256
from voxcpm_kaggle_worker import split_script


def audition_text(text,language):
    if "-->" in text:
        from voxcpm_kaggle_worker import parse_srt_cues
        cues=parse_srt_cues(text);base=cues[0]["start_ms"];selected=[]
        for cue in cues:
            if selected and cue["start_ms"]-base>=15000: break
            selected.append(cue)
        def stamp(ms):
            sec,millis=divmod(ms,1000);minutes,sec=divmod(sec,60);hours,minutes=divmod(minutes,60)
            return f"{hours:02}:{minutes:02}:{sec:02},{millis:03}"
        return "\n\n".join(f"{c['index']}\n{stamp(c['start_ms']-base)} --> {stamp(c['end_ms']-base)}\n{c['text']}" for c in selected)
    units=split_script(text,target_chars=1)
    target=70 if language in ("日语","粤语") else 180
    result=[];size=0
    for unit in units:
        if result and size+len(unit)>target: break
        result.append(unit);size+=len(unit)
    return " ".join(result)


def terminology_text(text,language,overrides=None):
    if language=="日语":
        from japanese_pronunciation import reading_plan,READINGS
        plan=reading_plan(text,overrides)
        terms=[item["term"] for item in plan["replacements"]]+plan["needs_context_review"]
    else:
        # User supplies terms; do not invent phonetic spellings for other languages.
        terms=[line.strip() for line in text.splitlines() if line.strip()]
    terms=list(dict.fromkeys(terms))
    if not terms: raise ValueError("没有找到待试听术语，请每行填写一个术语后再试。")
    return "。 ".join(terms)+"。" if language in ("日语","粤语") else ". ".join(terms)+"."


def load_segments(audio):
    path=Path(str(audio)+".segments.json")
    value=json.loads(path.read_text(encoding="utf-8"))
    if value.get("audio_sha256")!=file_sha256(audio): raise ValueError("句段时间表与音频不一致，请选择对应原音频。")
    with wave.open(str(audio),"rb") as source: duration=source.getnframes()/source.getframerate()
    last=0
    for item in value.get("segments",[]):
        a,b=float(item["start"]),float(item["end"])
        if not math.isfinite(a+b) or a<last-.002 or b<=a or b>duration+.05 or not isinstance(item["text"],str): raise ValueError("句段时间表无效。")
        last=b
    if not value.get("segments"): raise ValueError("音频没有句段时间表。")
    return value


def export_opening_preview(audio, target):
    """Export the opening generated unit, without another TTS call or pause removal."""
    record = load_segments(audio)
    end = min((item["end"] for item in record["segments"]),key=lambda value:abs(value-15))
    target = Path(target)
    pending = target.with_suffix(".wav.tmp")
    with wave.open(str(audio), "rb") as source, wave.open(str(pending), "wb") as destination:
        frames = min(source.getnframes(), round(end * source.getframerate()))
        destination.setparams(source.getparams())
        while frames:
            block = source.readframes(min(frames, 48000))
            if not block:
                raise ValueError("完整音频不足以导出试听。")
            destination.writeframes(block)
            frames -= len(block) // (source.getnchannels() * source.getsampwidth())
    pending.replace(target)
    return str(target)


def update_edited_segments(edit,replacement,target,timing):
    original=Path(edit.get("_prepared_segments",""))
    if not original.is_file(): return None
    record=json.loads(original.read_text(encoding="utf-8"))
    a,b=float(edit["start"]),float(edit["end"])
    units=record["segments"]
    if not any(abs(item["start"]-a)<.01 for item in units) or not any(abs(item["end"]-b)<.01 for item in units):
        return None  # A manually cut sub-unit cannot be assigned a made-up transcript.
    try: new=load_segments(replacement)
    except (OSError,ValueError): new={"segments":[{"start":0,"end":timing["replacement_seconds"],"text":edit["text"]}],"timing":"generated_units"}
    result=[]
    for item in units:
        if item["end"]<=a+.001:
            changed={**item,"end":min(item["end"],timing["old_start"])}
            if changed["end"]>changed["start"]: result.append(changed)
    for item in new["segments"]:
        result.append({**item,"start":item["start"]+timing["old_start"],"end":item["end"]+timing["old_start"]})
    for item in units:
        if item["start"]>=b-.001:
            changed={**item,"start":max(item["start"],timing["old_end"])+timing["delta"],"end":item["end"]+timing["delta"]}
            if changed["end"]>changed["start"]: result.append(changed)
    path=Path(str(target)+".segments.json")
    value={"audio_sha256":file_sha256(target),"timing":"edited_generated_units","segments":result}
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8")
    load_segments(target)
    return str(path)
