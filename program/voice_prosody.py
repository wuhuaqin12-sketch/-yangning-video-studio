"""Summarize rhythm only. Template waveforms never enter voice cloning."""
import hashlib
import subprocess
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent / "templates"
DEFAULTS = {"日语": "japanese.wav", "英语": "english.wav", "法语": "english.wav", "德语": "english.wav"}


def default_template(language):
    name = DEFAULTS.get(language)
    return str(ROOT / name) if name else ""


def analyze_template(path):
    """Approximate aggregate pauses and relative pitch spread, never absolute pitch."""
    from voice_clip_edit import tool
    path = Path(path)
    if not path.is_file():
        raise ValueError("请选择有效的语气模板音频。")
    result = subprocess.run([tool("ffmpeg"), "-v", "error", "-i", str(path),
                             "-t", "120", "-ar", "16000", "-ac", "1", "-f", "f32le", "pipe:1"],
                            check=True, capture_output=True, timeout=60)
    audio = np.frombuffer(result.stdout, dtype="<f4")
    frame = 320
    if len(audio) < 16000:
        raise ValueError("语气模板至少需要一秒有效音频。")
    windows = audio[:len(audio)//frame*frame].reshape(-1, frame)
    rms = np.sqrt(np.mean(windows.astype(float)**2, axis=1))
    peak = float(np.max(rms))
    if peak < 1e-5:
        raise ValueError("语气模板没有可分析的声音。")
    active = rms > max(peak * 0.07, 1e-5)
    voiced = np.flatnonzero(active)
    if len(voiced) < 10:
        raise ValueError("语气模板的有效语音太少。")
    # Count internal low-energy gaps only; no output audio is trimmed or retimed.
    silence = ~active[voiced[0]:voiced[-1]+1]
    edges = np.diff(np.r_[False, silence, False].astype(int))
    gaps = (np.flatnonzero(edges == -1)-np.flatnonzero(edges == 1))*0.02
    gaps = gaps[(gaps >= 0.12) & (gaps <= 2.5)]
    pitches = []
    for index in voiced[::max(1, len(voiced)//180)]:
        start = int(index)*frame
        x = audio[start:start+1024].astype(float)
        if len(x) < 1024:
            continue
        x = (x-x.mean())*np.hanning(1024)
        corr = np.correlate(x, x, mode="full")[1023:]
        lag = int(np.argmax(corr[40:267]))+40
        if corr[0] > 0 and corr[lag]/corr[0] > 0.55:
            pitches.append(16000/lag)
    spread = 0.0
    if len(pitches) >= 8:
        # Ratios discard the template speaker's absolute pitch.
        spread = float(12*np.log2(np.percentile(pitches, 80)/np.percentile(pitches, 20)))
    pause = float(np.median(gaps)) if len(gaps) else 0.25
    gap_style = "brief natural pauses" if pause < 0.45 else "unhurried natural breathing pauses"
    contour = "subtle, restrained rises and falls" if spread < 5 else "gentle, moderately varied rises and falls without exaggerated emphasis"
    instruction = f"Smooth connected phrasing, {gap_style}, {contour}, relaxed and gentle delivery"
    return {"method": "aggregate_acoustic_summary_to_text", "source_name": path.name,
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "analyzed_seconds": round(len(audio)/16000, 3), "median_internal_pause_seconds": round(pause, 3),
            "relative_pitch_spread_semitones": round(spread, 3), "instruction": instruction,
            "template_waveform_sent_to_model": False, "absolute_pitch_transferred": False,
            "tempo_changed_by_template": False, "exact_sentence_alignment": False}
