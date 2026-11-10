"""Reversible ordinary-audio adjustments and explicit generation style controls."""
import hashlib
import json
import math
import re
import uuid
from pathlib import Path
from voice_clip_edit import tool, command, probe

STYLE_OPTIONS = {
    "更柔和": "gentle relaxed delivery, without breathiness or forced emphasis",
    "更连贯": "smooth connected phrasing, retain natural sentence pauses",
    "更平和": "calm even delivery with restrained native intonation",
    "抑扬少一点": "subtle pitch variation, avoid dramatic rises and exaggerated emphasis",
    "停顿长一点": "slightly longer natural phrase and sentence pauses",
    "停顿短一点": "slightly shorter natural pauses, never rush words or remove all pauses",
    "重点更清楚": "clear restrained emphasis on meaningful words, without raising overall pitch",
    "像自然讲课": "natural conversational teaching, fluent and unforced",
}

PRESETS = {
    "自然": [],
    "柔和连贯": ["更柔和", "更连贯", "抑扬少一点"],
    "平和讲课": ["更平和", "更连贯", "像自然讲课"],
    "自定义": None,
}


def validate_options(tempo=1.0, gain_db=0.0, denoise=True, styles=None):
    tempo, gain_db = float(tempo), float(gain_db)
    if not math.isfinite(tempo) or not 0.5 <= tempo <= 2:
        raise ValueError("速度必须在0.5至2倍之间。")
    if not math.isfinite(gain_db) or not -12 <= gain_db <= 6:
        raise ValueError("音量调整范围为-12至+6 dB。")
    styles = list(dict.fromkeys(styles or []))
    if any(name not in STYLE_OPTIONS for name in styles):
        raise ValueError("包含未支持的语气选项。")
    if {"停顿长一点", "停顿短一点"}.issubset(styles):
        raise ValueError("停顿长一点和停顿短一点不能同时选择。")
    return {"tempo": tempo, "gain_db": gain_db, "denoise": bool(denoise), "styles": styles}


def interpret_instruction(text):
    """Only recognize listed controls; never silently claim to understand arbitrary text."""
    text = text.strip()
    options = {"tempo": 1.0, "gain_db": 0.0, "denoise": False}
    styles, unknown, specified, directions = [], [], set(), {}
    for piece in re.split(r"[，,；;。\n]+", text):
        piece = piece.strip()
        if not piece:
            continue
        if piece in STYLE_OPTIONS:
            styles.append(piece)
        elif piece in ("慢一点", "放慢一点"):
            options["tempo"] = 0.9
            specified.add("tempo"); directions.setdefault("tempo",set()).add("slow")
        elif piece in ("快一点", "加快一点"):
            options["tempo"] = 1.1
            specified.add("tempo"); directions.setdefault("tempo",set()).add("fast")
        elif piece in ("大声一点", "音量大一点"):
            options["gain_db"] = 2.0
            specified.add("gain_db"); directions.setdefault("gain_db",set()).add("up")
        elif piece in ("小声一点", "音量小一点"):
            options["gain_db"] = -2.0
            specified.add("gain_db"); directions.setdefault("gain_db",set()).add("down")
        elif piece in ("轻度降噪", "降噪"):
            options["denoise"] = True
            specified.add("denoise")
        else:
            unknown.append(piece)
    if any(len(values) > 1 for values in directions.values()):
        raise ValueError("同一指令中存在相反的速度或音量要求，请只保留一个方向。")
    validate_options(styles=styles)
    return {**options, "styles": list(dict.fromkeys(styles)), "unrecognized": unknown, "specified": sorted(specified)}

def style_instruction(names):
    validate_options(styles=names)
    return "; ".join(STYLE_OPTIONS[name] for name in dict.fromkeys(names))

def adjust_audio(source, output_dir, tempo=1.0, gain_db=0.0, denoise=False):
    options=validate_options(tempo,gain_db,denoise)
    tempo,gain_db=options["tempo"],options["gain_db"]
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError("请先选择需要微调的音频。")
    info=probe(source)
    streams=[x for x in info.get("streams",[]) if x.get("codec_type")=="audio"]
    if not streams:
        raise ValueError("文件中没有可处理的音轨。")
    channels=int(streams[0].get("channels",1))
    if channels not in (1,2):
        raise ValueError("普通微调支持单声道或双声道音频；多声道请先另存成所需声道。")
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    folder = Path(output_dir).resolve() / ("audio_adjust_" + uuid.uuid4().hex[:12])
    folder.mkdir(parents=True)
    target, partial = folder / "adjusted.wav", folder / "adjusted.partial.wav"
    filters = []
    if denoise:
        filters.append("afftdn=nr=6:nf=-45:tn=1")
    if tempo != 1:
        filters.append(f"rubberband=tempo={tempo}:pitch=1")
    if gain_db:
        filters.append(f"volume={gain_db}dB")
        if gain_db > 0:
            filters.append("alimiter=limit=0.95:level=0:latency=1")
    args = [tool("ffmpeg"), "-v", "error", "-y", "-i", str(source), "-vn", "-map", "0:a:0"]
    if filters:
        args += ["-af", ",".join(filters)]
    try:
        command(args + ["-ar", "48000", "-ac", str(channels), "-c:a", "pcm_s16le", str(partial)])
        command([tool("ffmpeg"), "-v", "error", "-xerror", "-i", str(partial), "-f", "null", "-"])
        if hashlib.sha256(source.read_bytes()).hexdigest()!=source_hash:
            raise ValueError("处理期间原音频发生变化，请重新选择该文件。")
        partial.replace(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    (folder / "adjustment.json").write_text(json.dumps({
        "source": str(source), "source_sha256": source_hash, "channels": channels, "result": str(target), "tempo": tempo, "gain_db": gain_db,
        "light_denoise": bool(denoise), "pitch_factor": 1, "silence_trimmed": False,
        "source_preserved": True, "speech_style_changed": False,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)
