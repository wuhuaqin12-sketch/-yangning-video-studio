"""Reversible ordinary-audio adjustments and explicit generation style controls."""
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

def interpret_instruction(text):
    """Only recognize listed controls; never silently claim to understand arbitrary text."""
    text = text.strip()
    options = {"tempo": 1.0, "gain_db": 0.0, "denoise": False}
    styles, unknown = [], []
    for piece in re.split(r"[，,；;。\n]+", text):
        piece = piece.strip()
        if not piece:
            continue
        if piece in STYLE_OPTIONS:
            styles.append(piece)
        elif piece in ("慢一点", "放慢一点"):
            options["tempo"] = 0.9
        elif piece in ("快一点", "加快一点"):
            options["tempo"] = 1.1
        elif piece in ("大声一点", "音量大一点"):
            options["gain_db"] = 2.0
        elif piece in ("小声一点", "音量小一点"):
            options["gain_db"] = -2.0
        elif piece in ("轻度降噪", "降噪"):
            options["denoise"] = True
        else:
            unknown.append(piece)
    return {**options, "styles": styles, "unrecognized": unknown}

def style_instruction(names):
    if any(name not in STYLE_OPTIONS for name in names):
        raise ValueError("包含未支持的语气选项。")
    return "; ".join(STYLE_OPTIONS[name] for name in dict.fromkeys(names))

def adjust_audio(source, output_dir, tempo=1.0, gain_db=0.0, denoise=False):
    tempo, gain_db = float(tempo), float(gain_db)
    if not math.isfinite(tempo) or not 0.5 <= tempo <= 2:
        raise ValueError("速度必须在0.5至2倍之间。")
    if not math.isfinite(gain_db) or not -12 <= gain_db <= 6:
        raise ValueError("音量调整范围为-12至+6 dB。")
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError("请先选择需要微调的音频。")
    probe(source)
    folder = Path(output_dir).resolve() / ("audio_adjust_" + uuid.uuid4().hex[:12])
    folder.mkdir(parents=True)
    target, partial = folder / "adjusted.wav", folder / "adjusted.partial.wav"
    filters = []
    if denoise:
        filters.append("afftdn=nr=6:nf=-45:tn=1")
    if tempo != 1:
        filters.append(f"rubberband=tempo={tempo}:pitch=1")
    if gain_db:
        filters.extend([f"volume={gain_db}dB", "alimiter=limit=0.95:level=0:latency=1"])
    args = [tool("ffmpeg"), "-v", "error", "-y", "-i", str(source), "-vn", "-map", "0:a:0"]
    if filters:
        args += ["-af", ",".join(filters)]
    try:
        command(args + ["-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(partial)])
        command([tool("ffmpeg"), "-v", "error", "-xerror", "-i", str(partial), "-f", "null", "-"])
        partial.replace(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    (folder / "adjustment.json").write_text(json.dumps({
        "source": str(source), "result": str(target), "tempo": tempo, "gain_db": gain_db,
        "light_denoise": bool(denoise), "pitch_factor": 1, "silence_trimmed": False,
        "source_preserved": True, "speech_style_changed": False,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)
