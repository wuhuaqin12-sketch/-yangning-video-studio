"""Summarize rhythm only. Template waveforms never enter voice cloning."""
import hashlib
import subprocess
import shutil
import uuid
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent / "templates"
DEFAULTS = {"日语": "japanese.wav", "英语": "english.wav", "法语": "english.wav", "德语": "english.wav"}


def default_template(language):
    name = DEFAULTS.get(language)
    return str(ROOT / name) if name else ""


NATIVE_NAMES={"日语":"japanese.wav","英语":"english.wav","法语":"french.wav","德语":"german.wav",
              "粤语":"cantonese.wav","印尼语":"indonesian.wav"}
TEMPLATE_MODES=("自动选择","手动指定","自然语气（无模板）")


def restore_template_path(language, saved_path, saved_mode=None):
    """Repair moved built-ins only; explicit manual choices must never change."""
    if saved_mode=="手动指定": return saved_path
    if saved_path and not Path(saved_path).is_file() and Path(saved_path).name in ("japanese.wav","english.wav"):
        return default_template(language)
    return saved_path


def choose_template(language, mode="自动选择", manual_path="", template_root=None):
    """Match explicitly language-labelled local assets; no language/voice guessing."""
    if language not in NATIVE_NAMES:
        raise ValueError("当前模型入口尚未配置此语言，不能仅靠模板选择宣称支持。")
    if mode not in TEMPLATE_MODES:
        raise ValueError("请选择有效的语气模板模式。")
    root=Path(template_root) if template_root is not None else ROOT
    result={"mode":mode,"language":language,"path":"","source_kind":"natural_preset",
            "template_language":None,"waveform_sent_to_model":False}
    if mode=="自然语气（无模板）":
        result["description"]=f"{language}自然语气预设 · 未使用音频模板"
        return result
    if mode=="手动指定":
        if not str(manual_path).strip() or not Path(manual_path).is_file():
            raise ValueError("手动模式请先选择有效模板；不会默默改用其他音频。")
        result.update(path=str(Path(manual_path).resolve()),source_kind="manual",description="手动模板："+Path(manual_path).name+" · 仅节奏摘要")
        return result
    native=root/NATIVE_NAMES[language]
    if not native.is_file() and (ROOT/NATIVE_NAMES[language]).is_file(): native=ROOT/NATIVE_NAMES[language]
    english=root/"english.wav"
    if not english.is_file(): english=ROOT/"english.wav"
    if native.is_file():
        result.update(path=str(native.resolve()),source_kind="language_labelled",template_language=language,
                      description=f"自动：{language}标签模板 {native.name} · 仅节奏摘要")
    elif language in ("法语","德语") and english.is_file():
        result.update(path=str(english.resolve()),source_kind="approved_rhythm_fallback",template_language="英语",
                      description=f"自动：暂缺{language}模板，参考英语模板的节奏摘要 · 发音及语感仍用{language}预设")
    else:
        result["description"]=f"自动：暂缺{language}模板，使用{language}自然语气预设 · 未使用音频模板"
    return result


def install_language_template(language,source,directory):
    if language not in NATIVE_NAMES: raise ValueError("语言未支持。")
    summary=analyze_template(source)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    target=directory/NATIVE_NAMES[language]
    pending=directory/("template_"+uuid.uuid4().hex+".tmp")
    # Normalize container/codec without changing the template's voice input role.
    # It remains local analysis only, never the cloning speaker reference.
    from voice_clip_edit import tool
    subprocess.run([tool("ffmpeg"),"-v","error","-y","-i",str(source),"-t","120","-ar","48000","-ac","1","-c:a","pcm_s16le","-f","wav",str(pending)],check=True,capture_output=True,timeout=120)
    if target.is_file(): shutil.copy2(target,directory/(target.stem+"_previous.wav"))
    pending.replace(target)
    return str(target)


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
