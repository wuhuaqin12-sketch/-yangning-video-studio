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
