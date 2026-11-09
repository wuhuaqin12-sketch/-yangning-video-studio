"""Local, reversible assembly of a regenerated passage into a complete clip."""
import json
import math
import re
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

RATE = 48000


def tool(name):
    try:
        from media import executable
        return executable(name)
    except ImportError:
        found = shutil.which(name)
        if not found:
            raise RuntimeError(f"缺少{name}，无法合成完整短片。")
        return found


def command(args):
    result = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-2400:])
    return result.stdout


def probe(path):
    return json.loads(command([tool("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))


def wav_info(path):
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, RATE):
            raise ValueError("拼接输入需要48kHz单声道PCM16 WAV。")
        return wav.getnframes(), wav.getnframes() / RATE


def read_frames(path, start, end):
    with wave.open(str(path), "rb") as wav:
        start = min(max(0, int(start)), wav.getnframes())
        end = min(max(start, int(end)), wav.getnframes())
        wav.setpos(start)
        return np.frombuffer(wav.readframes(end - start), dtype="<i2").astype(np.float32) / 32768.0


def quiet_edge(path, boundary, side, radius=0.30):
    """Search outward from the selected sentence for a quiet 20ms boundary."""
    frames, duration = wav_info(path)
    if side == "start" and boundary <= 0.001:
        return 0
    if side == "end" and boundary >= duration - 0.001:
        return frames
    center = round(boundary * RATE)
    window = round(0.020 * RATE)
    for distance in range(0, round(radius * RATE) + 1, round(0.005 * RATE)):
        point = center - distance if side == "start" else center + distance
        if point < window or point + window > frames:
            continue
        values = read_frames(path, point - window // 2, point + window // 2)
        if np.sqrt(np.mean(values * values)) <= 0.006 and np.max(np.abs(values)) <= 0.025:
            return point
    raise ValueError("选定句段附近没有足够安静的接点，请把范围扩大到完整句子及前后停顿，再重新生成。")


def _copy_frames(src, dst, start, end, gain=1.0):
    src.setpos(start)
    remaining = end - start
    while remaining > 0:
        count = min(remaining, RATE * 2)
        data = src.readframes(count)
        if len(data) != count * 2:
            raise ValueError("音频读取不完整。")
        if gain != 1.0:
            data = np.rint(np.frombuffer(data, dtype="<i2").astype(np.float64) * gain).clip(-32768, 32767).astype("<i2").tobytes()
        dst.writeframesraw(data)
        remaining -= count


def _write_faded(src, dst, start, end, fade_in=False, fade_out=False, gain=1.0):
    length = end - start
    fade = min(round(0.005 * RATE), length // 2)
    if not fade:
        _copy_frames(src, dst, start, end, gain)
        return
    def edge(a, b, ramp):
        src.setpos(a)
        values = np.frombuffer(src.readframes(b - a), dtype="<i2").astype(np.float64)
        dst.writeframesraw(np.rint(values * ramp * gain).clip(-32768, 32767).astype("<i2").tobytes())
    if fade_in:
        edge(start, start + fade, np.linspace(0, 1, fade))
        start += fade
    tail = end - fade if fade_out else end
    _copy_frames(src, dst, start, tail, gain)
    if fade_out:
        edge(tail, end, np.linspace(1, 0, fade))


def patch_audio(original, replacement, output, start, end, snap=True):
    frames, duration = wav_info(original)
    replacement_frames, replacement_duration = wav_info(replacement)
    if not (0 <= start < end <= duration + 0.001):
        raise ValueError("替换范围必须在当前成片的音频时长内。")
    a = quiet_edge(original, start, "start") if snap else round(start * RATE)
    b = quiet_edge(original, end, "end") if snap else min(frames, round(end * RATE))
    for edge, required in (("start", a > 0), ("end", b < frames)):
        if not required:
            continue
        values = read_frames(replacement, 0, 960) if edge == "start" else read_frames(replacement, replacement_frames - 960, replacement_frames)
        if not len(values) or np.sqrt(np.mean(values * values)) > 0.008 or np.max(np.abs(values)) > 0.04:
            raise ValueError("新配音的句首或句尾没有自然停顿，无法安全接回。请连同完整句子和呼吸停顿重新生成。")
    def active_level(path, first, last):
        energy, count, peak = 0.0, 0, 0.0
        for pos in range(first, last, RATE * 2):
            values = read_frames(path, pos, min(last, pos + RATE * 2))
            active = values[np.abs(values) > 0.015]
            energy += float(np.sum(active.astype(np.float64) ** 2))
            count += len(active)
            peak = max(peak, float(np.max(np.abs(values))) if len(values) else 0.0)
        return math.sqrt(energy / count) if count else 0.0, peak
    old_level, _ = active_level(original, a, b)
    new_level, new_peak = active_level(replacement, 0, replacement_frames)
    gain = 1.0
    if a > 0 or b < frames:
        if old_level > 0 and new_level > 0:
            gain = min(10 ** (3 / 20), max(10 ** (-3 / 20), old_level / new_level))
            if new_peak:
                gain = min(gain, 0.99 / new_peak)
    with wave.open(str(original), "rb") as src, wave.open(str(replacement), "rb") as clip, wave.open(str(output), "wb") as dst:
        dst.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        if a:
            _write_faded(src, dst, 0, a, fade_out=True)
        _write_faded(clip, dst, 0, replacement_frames, fade_in=a > 0, fade_out=b < frames, gain=gain)
        if b < frames:
            _write_faded(src, dst, b, frames, fade_in=True)
    return {
        "requested_start": start, "requested_end": end, "old_start": a / RATE, "old_end": b / RATE,
        "replacement_seconds": replacement_duration, "old_seconds": duration,
        "new_seconds": (frames - (b - a) + replacement_frames) / RATE,
        "delta": replacement_duration - (b - a) / RATE,
        "quiet_boundary_fade_ms": 5, "crossfade_speech": False,
        "replacement_samples_removed": 0, "review_status": "接缝待听检",
        "replacement_gain": gain, "level_match_limit_db": 3,
    }


def read_srt(path):
    def seconds(value):
        h, m, s = value.replace(",", ".").split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    cues = []
    for block in re.split(r"\n\s*\n", Path(path).read_text(encoding="utf-8-sig").strip()):
        lines = block.strip().splitlines()
        index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if index is None:
            raise ValueError("字幕包含没有时间码的段落。")
        parts = lines[index].split("-->")
        a, b = seconds(parts[0].strip()), seconds(parts[1].strip().split()[0])
        if not 0 <= a < b:
            raise ValueError("字幕时间范围错误。")
        cues.append({"start": a, "end": b, "text": "\n".join(lines[index + 1:])})
    if any(cues[i]["start"] < cues[i - 1]["start"] for i in range(1, len(cues))):
        raise ValueError("字幕未按时间排序。")
    return cues


def write_srt(cues, path):
    def clock(value):
        total = max(0, round(value * 1000))
        hours, total = divmod(total, 3600000)
        minutes, total = divmod(total, 60000)
        seconds, ms = divmod(total, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"
    Path(path).write_text("\n\n".join(f"{i+1}\n{clock(c['start'])} --> {clock(c['end'])}\n{c['text']}" for i, c in enumerate(cues)) + "\n", encoding="utf-8")


def remap_subtitles(cues, timing, text):
    a, b = timing["old_start"], timing["old_end"]
    delta, new_length = timing["delta"], timing["replacement_seconds"]
    before, after = [], []
    for cue in cues:
        if cue["end"] <= a + 0.002:
            before.append(dict(cue))
        elif cue["start"] >= b - 0.002:
            after.append({**cue, "start": cue["start"] + delta, "end": cue["end"] + delta})
        elif cue["start"] < a - 0.03 or cue["end"] > b + 0.03:
            raise ValueError("替换范围切进了字幕句子，请选择完整字幕句段。")
    # Sentence timings inside the new passage are estimates, explicitly recorded.
    sentences = [x.strip() for x in re.split(r"(?<=[。！？.!?])\s+|(?<=[。！？])", text) if x.strip()]
    if not sentences:
        raise ValueError("修改后的正文为空。")
    weights = [max(1, len(s)) for s in sentences]
    cursor, replacement = a, []
    for sentence, weight in zip(sentences, weights):
        end = cursor + new_length * weight / sum(weights)
        replacement.append({"start": cursor, "end": end, "text": sentence})
        cursor = end
    return before + replacement + after


def _video_graph(timing, video_duration, fps):
    a, b, length = timing["old_start"], timing["old_end"], timing["replacement_seconds"]
    sections = []
    ranges = []
    if a > 0.00001:
        ranges.append((0, a, 1.0))
    ranges.append((a, b, length / (b - a)))
    if b < video_duration - 0.00001:
        ranges.append((b, video_duration, 1.0))
    pieces = [f"[0:v]split={len(ranges)}" + "".join(f"[s{i}]" for i in range(len(ranges)))]
    for i, (start, end, ratio) in enumerate(ranges):
        pieces.append(f"[s{i}]trim=start={start:.9f}:end={end:.9f},setpts=(PTS-STARTPTS)*{ratio:.12f},fps={fps},settb=AVTB[v{i}]")
        sections.append(f"[v{i}]")
    pieces.append("".join(sections) + f"concat=n={len(ranges)}:v=1:a=0,tpad=stop_mode=clone:stop_duration=1,trim=duration={timing['new_seconds']:.9f},pad=ceil(iw/2)*2:ceil(ih/2)*2[v]")
    return ";".join(pieces)


def preflight_edit(edit):
    video = Path(edit["video"])
    if not video.is_file():
        raise ValueError("当前成片视频不存在。")
    metadata = probe(video)
    duration = float(metadata["format"]["duration"])
    if edit["mode"] not in ("full", "partial"):
        raise ValueError("请选择局部重做或全文重做。")
    if edit["mode"] == "partial" and not 0 <= float(edit["start"]) < float(edit["end"]) <= duration + 0.05:
        raise ValueError("选定句段超出当前视频时长，未提交GPU任务。")
    if edit.get("audio"):
        audio_metadata = probe(edit["audio"])
        if abs(float(audio_metadata["format"]["duration"]) - duration) > 0.2:
            raise ValueError("所选独立配音与当前视频时长不一致，未提交GPU任务。")
    elif not any(s["codec_type"] == "audio" for s in metadata["streams"]):
        raise ValueError("当前视频没有声音，请选择与其对齐的独立配音WAV。")
    if edit.get("srt"):
        read_srt(edit["srt"])


def export_edited_clip(edit, replacement, target_dir, job_id, progress=lambda value: None):
    target = Path(target_dir)
    folder = target / ("VoiceEdit_" + job_id)
    folder.mkdir(parents=True, exist_ok=True)
    report_path = folder / "edit_report.json"
    report = {"status": "preparing", "original_video": edit["video"], "original_audio": edit.get("audio", ""), "original_srt": edit.get("srt", ""), "replacement": str(replacement), "mode": edit["mode"], "review": "待听检与画面核对"}
    try:
        video = Path(edit["video"])
        if not video.is_file():
            raise ValueError("请选择需要修改的当前完整短片。")
        metadata = probe(video)
        stream = next((s for s in metadata["streams"] if s["codec_type"] == "video"), None)
        if not stream:
            raise ValueError("输入文件没有视频画面。")
        vd = float(stream.get("duration") or metadata["format"]["duration"])
        ratio = stream.get("avg_frame_rate", "30/1").split("/")
        fps_value = float(ratio[0]) / float(ratio[1]) if len(ratio) == 2 and float(ratio[1]) else 30
        fps = max(1.0, min(120.0, fps_value))
        original = folder / "source_audio.wav"
        progress("正在准备原片配音轨…")
        command([tool("ffmpeg"), "-v", "error", "-y", "-i", str(edit.get("audio") or video), "-vn", "-map", "0:a:0", "-ar", str(RATE), "-ac", "1", "-c:a", "pcm_s16le", str(original)])
        frames, duration = wav_info(original)
        if abs(vd - duration) > max(0.20, 2 / fps):
            raise ValueError("当前视频与所选配音的时间轴不一致，请使用已对齐的当前成片，或选择与其时长一致的独立配音。")
        start, end = (0, duration) if edit["mode"] == "full" else (float(edit["start"]), float(edit["end"]))
        edited_audio = folder / "complete_audio.wav"
        timing = patch_audio(original, replacement, edited_audio, start, end, snap=edit["mode"] != "full")
        report["timing_map"] = timing
        srt = folder / "complete_subtitles.srt"
        cues = read_srt(edit["srt"]) if edit.get("srt") else []
        if cues and max(c["end"] for c in cues) > duration + 0.25:
            raise ValueError("字幕超出当前成片时间轴，请选择配套SRT。")
        if edit["mode"] == "full":
            cues = []
        write_srt(remap_subtitles(cues, timing, edit["text"]), srt)
        report["subtitle_timing"] = "区间外字幕按时间差平移；新区间按句子长度估算，待校对；不烧录字幕"
        progress("正在重新合成完整短片…")
        partial = folder / "complete_video.partial.mp4"
        graph = _video_graph(timing, vd, fps)
        command([tool("ffmpeg"), "-v", "error", "-y", "-filter_complex_threads", "1", "-i", str(video), "-i", str(edited_audio),
                 "-filter_complex", graph, "-map", "[v]", "-map", "1:a:0", "-c:v", "libx264", "-threads", "2", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-t", f"{timing['new_seconds']:.9f}", "-movflags", "+faststart", str(partial)])
        command([tool("ffmpeg"), "-v", "error", "-xerror", "-i", str(partial), "-f", "null", "-"])
        actual = float(probe(partial)["format"]["duration"])
        if abs(actual - timing["new_seconds"]) > max(0.12, 2 / fps):
            raise ValueError("成片时长与拼接音频不一致，未将该文件标记为完成。")
        final = folder / "complete_video.mp4"
        partial.replace(final)
        for name, moment in (("join_left", timing["old_start"]), ("join_right", timing["old_start"] + timing["replacement_seconds"])):
            if moment <= 0 or moment >= timing["new_seconds"]:
                continue
            values = read_frames(edited_audio, max(0, round((moment - 0.8) * RATE)), round(min(timing["new_seconds"], moment + 0.8) * RATE))
            with wave.open(str(folder / (name + ".wav")), "wb") as wav:
                wav.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
                wav.writeframes(np.rint(values * 32768).clip(-32768, 32767).astype("<i2").tobytes())
        report.update(status="exported_pending_review", exported_seconds=actual, video=str(final), audio=str(edited_audio), subtitles=str(srt))
        return {"edited_video": str(final), "edited_audio": str(edited_audio), "edited_srt": str(srt), "edit_report": str(report_path)}
    except Exception as exc:
        report.update(status="failed_recoverable", error=str(exc))
        raise
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
