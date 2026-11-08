"""Voice 1626 policy and instruction controls.

This module deliberately does not synthesize audio. A compatible voice-cloning
engine must be integrated and tested before the UI offers generation.
"""
from dataclasses import dataclass
from pathlib import Path

LANGUAGES = {
    "ja": "日语", "en": "英语", "fr": "法语",
    "de": "德语", "id": "印尼语", "yue": "粤语",
}
DEFAULT_INSTRUCTIONS = (
    "只以1626老师原声作为音色参考。保持原声音色，不混合任何语气模板的音色。"
    "采用自然、沉稳、温和的讲经语气，按句义安排重音和抑扬顿挫。"
    "逗号短停、句号稍长停、段落自然呼吸。避免机械朗读、夸张情绪、"
    "过长尾音。使用目标语言母语习惯的发音、语调和节奏。"
)

@dataclass(frozen=True)
class VoiceSettings:
    reference_audio: str
    language: str = "ja"
    speed: float = 1.0
    instructions: str = DEFAULT_INSTRUCTIONS

    def validate(self):
        if self.language not in LANGUAGES:
            raise ValueError("不支持的配音语言")
        if not 0.5 <= self.speed <= 2.0:
            raise ValueError("语速须在0.5至2.0之间")
        if not self.reference_audio or not Path(self.reference_audio).is_file():
            raise ValueError("请先提供1626原声音频")
        if not self.instructions.strip():
            raise ValueError("配音指令不能为空")
        return self

def synthesis_request(text, settings):
    """Validated engine-neutral request; never pass a style reference audio."""
    settings.validate()
    if not isinstance(text, str) or not text.strip():
        raise ValueError("请输入配音文字")
    return {
        "text": text.strip(),
        "language": settings.language,
        "voice_reference_audio": str(Path(settings.reference_audio).resolve()),
        "instructions": settings.instructions.strip(),
        "speed": settings.speed,
    }


def read_text_file(path):
    path = Path(path)
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeError:
            continue
    raise ValueError("文件编码无法识别")


def parse_srt_cues(source):
    """Read SRT captions while deliberately discarding old timestamps."""
    import re
    source = source.replace("\\r\\n", "\\n").replace("\\r", "\\n")
    blocks = re.split(r"\\n\\s*\\n", source.strip())
    cues = []
    timing = re.compile(r"^\\d{2}:\\d{2}:\\d{2}[,.]\\d{3}\\s*-->")
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if lines and lines[0].isdigit():
            lines.pop(0)
        if lines and timing.match(lines[0]):
            lines.pop(0)
        if lines:
            cues.append(" ".join(lines))
    return cues


def load_script(path):
    """Read TXT/SRT text without reading original SRT timestamps aloud."""
    path = Path(path)
    if path.suffix.lower() not in (".txt", ".srt"):
        raise ValueError("只支持 TXT 或 SRT 文件")
    raw = read_text_file(path)
    return ("\\n".join(parse_srt_cues(raw)) if path.suffix.lower() == ".srt"
            else raw.strip())


def split_script(text, max_chars=220):
    """Split long text for synthesis without imposing a total length cap."""
    import re
    if max_chars < 20:
        raise ValueError("每段字符数过小")
    chunks = []
    for paragraph in text.splitlines():
        for sentence in re.split(r"(?<=[。！？!?；;])", paragraph):
            sentence = sentence.strip()
            while sentence:
                space = max_chars - len(chunks[-1]) - 1 if chunks else 0
                if chunks and space > 0 and len(sentence) <= space:
                    chunks[-1] += " " + sentence
                    break
                chunks.append(sentence[:max_chars])
                sentence = sentence[max_chars:]
    return [c for c in chunks if c.strip()]


def format_srt_time(seconds):
    ms = max(0, round(seconds * 1000))
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def build_srt_from_durations(cues, durations, gap_seconds=0.3):
    """Create a NEW SRT from generated audio segment lengths, not old times."""
    if len(cues) != len(durations):
        raise ValueError("字幕数量与音频片段数量不一致")
    out = []
    cursor = 0.0
    for index, (cue, duration) in enumerate(zip(cues, durations), 1):
        if duration <= 0:
            raise ValueError("音频片段时长无效")
        end = cursor + duration
        out.append(f"{index}\\n{format_srt_time(cursor)} --> {format_srt_time(end)}\\n{cue}\\n")
        cursor = end + (gap_seconds if index < len(cues) else 0)
    return "\\n".join(out)

def apply_pronunciation_rules(text, rules):
    """Change spoken input only; keep the original text for subtitles."""
    if not isinstance(rules, dict):
        raise ValueError("发音词典格式错误")
    for written, spoken in sorted(rules.items(), key=lambda item: len(item[0]), reverse=True):
        if not written or not isinstance(spoken, str) or not spoken.strip():
            raise ValueError("发音词典中的原词和读法不能为空")
        text = text.replace(written, spoken.strip())
    return text


def load_pronunciation_rules(path, language):
    import json
    if language not in LANGUAGES:
        raise ValueError("未知语言")
    path = Path(path)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get(language, {})


def save_pronunciation_rules(path, language, rules):
    import json
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data[language] = rules
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
