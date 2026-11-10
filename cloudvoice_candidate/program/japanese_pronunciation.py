"""Deterministic reading text for Japanese TTS; the displayed script stays intact."""
import re
from collections import Counter

VERSION = "ja-dharma-20261110-v1"
# Project choices from Japanese_Kanji_Reading_Review.md (2026-11-07),
# supplemented by standard compound readings. Whole phrases take precedence.
READINGS = {
    "金剛般若波羅蜜経":"こんごうはんにゃはらみつきょう",
    "金剛般若波羅蜜多経":"こんごうはんにゃはらみったきょう",
    "金剛経":"こんごうきょう", "金剛經":"こんごうきょう",
    "鳩摩羅什":"くまらじゅう", "玄奘":"げんじょう",
    "般若波羅蜜":"はんにゃはらみつ", "般若心経":"はんにゃしんぎょう",
    "般若":"はんにゃ", "波羅蜜":"はらみつ",
    "無上正等正覚":"むじょうしょうとうしょうがく",
    "生死輪廻":"しょうじりんね", "輪廻":"りんね",
    "阿難尊者":"あなんそんじゃ", "大菩薩":"だいぼさつ", "菩薩":"ぼさつ",
    "菩提心":"ぼだいしん", "仏法":"ぶっぽう", "仏陀":"ぶっだ",
    "如来":"にょらい", "涅槃":"ねはん", "法身":"ほっしん",
    "解脱":"げだつ", "衆生":"しゅじょう", "誓願":"せいがん",
    "欲界":"よくかい", "三悪道":"さんあくどう", "三界":"さんがい",
    "正見":"しょうけん", "智慧":"ちえ", "共業":"ぐうごう",
    "空性":"くうしょう", "執着":"しゅうじゃく", "煩悩":"ぼんのう",
    "覚者":"かくしゃ", "極楽":"ごくらく", "善法":"ぜんぽう",
    "成就":"じょうじゅ", "修行":"しゅぎょう", "無我":"むが",
    "慈悲心":"じひしん", "慈悲":"じひ", "禅定":"ぜんじょう",
    "第一義諦":"だいいちぎたい", "拙火":"トゥンモ",
    "善い行い":"よいおこない", "利する":"りする",
    "すべての相":"すべてのそう", "相への執着":"そうへのしゅうじゃく",
}
# Contextual/rare readings are shown for manual review, never guessed.
REVIEW_TERMS = ("聞性", "本明", "本定", "第一念", "凝神", "軽安", "見性起修")


def parse_overrides(text):
    result = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"读音表第{number}行应为：汉字词语=假名读音")
        term, reading = (part.strip() for part in line.split("=", 1))
        if not term or not reading or not re.fullmatch(r"[ぁ-ゖァ-ヺー・ 　]+", reading):
            raise ValueError(f"读音表第{number}行请填写有效词语和假名读音。")
        if term in result:
            raise ValueError(f"读音表第{number}行重复了词语：{term}")
        result[term] = reading
    return result


def reading_plan(text, overrides=None):
    overrides = overrides or {}
    # Validate saved settings as well as GUI input. Never accept executable rules.
    validated = parse_overrides("\n".join(f"{k}={v}" for k,v in overrides.items()))
    table = {**READINGS, **validated}
    pattern = re.compile("|".join(re.escape(k) for k in sorted(table, key=len, reverse=True)))
    counts = Counter()
    def replace(match):
        term = match.group(0)
        counts[term] += 1
        return table[term]
    spoken = pattern.sub(replace, text)
    pending = [term for term in REVIEW_TERMS if term in text and term not in validated]
    return {"version":VERSION, "reading_text":spoken,
            "replacements":[{"term":term,"reading":table[term],"count":count} for term,count in counts.items()],
            "needs_context_review":pending, "display_text_changed":False,
            "review_status":"待音频听检"}
