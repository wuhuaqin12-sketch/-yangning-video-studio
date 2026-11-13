"""Insert punctuation pauses into ONE existing utterance; never synthesize speech.

MMS acoustic alignment locates words. Subtitle deadlines and character/time ratios
are deliberately not inputs. Heavy imports are confined to the engine process.
"""
import hashlib
import math
import os
import re
import unicodedata
from pathlib import Path

POLICY = "aligned_punctuation_minimum_v1"
DEPENDENCIES = ("uroman==1.3.1.1", "pykakasi==2.3.0", "pycantonese==4.0.0", "num2words==0.5.14")
MODEL_URL = "https://dl.fbaipublicfiles.com/mms/torchaudio/ctc_alignment_mling_uroman/model.pt"
MODEL_SHA256 = "20ef12963ab4924bef49ac4fc7f58ad5da2ee43b2c11bc8c853c9b90ecdbc680"
LANGUAGES = {"日语":"ja", "英语":"en", "法语":"fr", "德语":"de", "印尼语":"id", "粤语":"ja"}


def phrases(text):
    """Text spans for alignment ONLY. Consecutive marks share one boundary."""
    text = unicodedata.normalize("NFKC", text)
    result, start = [], 0
    for i, char in enumerate(text):
        pause = .30 if char in ",、，" else .60 if char in "。!?！？;；" else .70 if char == "\n" else 0
        if char == ".":
            before, after = text[:i], text[i+1:]
            abbreviation = re.search(r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\.g|i\.e)$", before, re.I)
            abbreviation = abbreviation or re.search(r"\b[A-HJ-Z]$|(?:\b[A-Z]\.)+[A-Z]$", before)
            decimal = bool(before and after and before[-1].isdigit() and after[0].isdigit())
            if not decimal and not abbreviation and (not after or after[0].isspace() or after[0].isupper() or ord(after[0])>127 or after[0] in '\"”」』'):
                pause = .60
        if char == "," and i and i+1 < len(text) and text[i-1].isdigit() and text[i+1].isdigit():
            pause = 0  # 1,000 is a number, not a clause boundary.
        if not pause:
            continue
        content = text[start:i].strip(' \t\r\n\"“”「」『』,、，。.!?！？;；')
        if content:
            result.append({"text":content, "minimum_seconds":pause})
        elif result:
            result[-1]["minimum_seconds"] = max(result[-1]["minimum_seconds"], pause)
        start = i+1
    tail = text[start:].strip(' \t\r\n\"“”「」『』,、，。.!?！？;；')
    if tail:
        result.append({"text":tail, "minimum_seconds":0.0})
    return result


def alignment_words(records, language):
    """Keep numbers; Japanese kanji and Cantonese use their own readings."""
    from num2words import num2words
    import uroman
    if language not in LANGUAGES:
        raise ValueError("停顿定位语言不受支持。")
    romanizer = uroman.Uroman()
    if language == "日语":
        from pykakasi import kakasi
        japanese = kakasi()
    if language == "粤语":
        import pycantonese
    words, indexed = [], []
    for record in records:
        text = record["text"]
        def number(match):
            value = match.group().replace(",", "")
            if len(value) > 15:
                raise ValueError("停顿定位遇到过长数字，请写成实际朗读文字；原始声音会保留。")
            return " " + num2words(float(value) if "." in value else int(value), lang=LANGUAGES[language]) + " "
        text = re.sub(r"\d+(?:,\d{3})*(?:\.\d+)?", number, text)
        if language == "日语":
            text = " ".join(part["hepburn"] for part in japanese.convert(text))
        elif language == "粤语":
            parts = []
            for part in re.findall(r"[\u3400-\u9fff]+|[^\u3400-\u9fff]+", text):
                if re.search(r"[\u3400-\u9fff]", part):
                    for original, reading in pycantonese.characters_to_jyutping(part):
                        if reading is None:
                            raise ValueError("粤语停顿定位遇到未知读音：" + original + "；保留原始声音，请检查文字。")
                        parts.append(re.sub(r"[1-6]", " ", reading))
                else:
                    parts.append(part)
            text = " ".join(parts)
        text = romanizer.romanize_string(text).lower().replace("’", "'")
        if re.search(r"\d|[\u3400-\u9fff\u3040-\u30ff]", text):
            raise ValueError("停顿定位读音归一化不完整；未丢弃文字或猜测时间。")
        tokens = re.sub(r"[^a-z' ]", " ", text).split()
        tokens = [token for token in tokens if re.search("[a-z]", token)]
        if not tokens:
            raise ValueError("有一段正文无法定位读音；请检查符号或文字。")
        begin = len(words)
        words.extend(tokens)
        indexed.append({**record, "first_word":begin, "last_word":len(words)-1})
    return words, indexed


def acoustic_alignment(waveform, rate, words):
    import torch
    import torchaudio
    # A fixed, checksum-verified model in a separate cache; no replacement of VoxCPM.
    cache = Path(os.environ.get("YANGNING_PAUSE_CACHE", str(Path.home()/".cache/yangning_pause")))
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / "model.pt"
    def digest(p):
        value = hashlib.sha256()
        with p.open("rb") as stream:
            for chunk in iter(lambda:stream.read(1024*1024), b""):
                value.update(chunk)
        return value.hexdigest()
    if not path.is_file() or digest(path) != MODEL_SHA256:
        print("首次停顿定位需下载约1.2GB定位模型；原有克隆模型保持缓存。", flush=True)
        pending = cache / "model.pt.pending"
        torch.hub.download_url_to_file(MODEL_URL, str(pending), hash_prefix=MODEL_SHA256, progress=False)
        pending.replace(path)
    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model(dl_kwargs={"model_dir":str(cache), "progress":False}).eval()
    wave = torch.as_tensor(waveform, dtype=torch.float32).reshape(1,-1)
    if rate != bundle.sample_rate:
        wave = torchaudio.functional.resample(wave, rate, bundle.sample_rate)
    # Bound attention memory: 20s core chunks with 1s acoustic context, fixed stride.
    sr = bundle.sample_rate
    stride = 320
    emissions = []
    with torch.inference_mode():
        for start in range(0, wave.shape[1], 20*sr):
            end = min(wave.shape[1], start+20*sr)
            left, right = max(0,start-sr), min(wave.shape[1],end+sr)
            emission, _ = model(wave[:,left:right])
            first = (start-left)//stride
            last = (end-left)//stride if right < wave.shape[1] else emission.shape[1]
            emissions.append(emission[0,first:last].cpu())
    del model
    emission = torch.cat(emissions)
    # The aligner's dynamic program must fit; never fall back to proportional timing.
    if emission.shape[0] * sum(len(word) for word in words) > 60_000_000:
        raise ValueError("正文过长，超出本次精确停顿定位容量；原始整段声音已保留，未拆句重克隆。")
    spans = bundle.get_aligner()(emission, bundle.get_tokenizer()(words))
    if len(spans) != len(words):
        raise ValueError("停顿定位文字数量不一致；未猜测时间或修改原音。")
    result = []
    for word, ss in zip(words,spans):
        if not ss:
            raise ValueError("停顿定位缺少文字对应的声音；保留完整原音，未猜测停顿位置。")
        result.append({"word":word, "start":ss[0].start*stride/sr,
                       "end":ss[-1].end*stride/sr,
                       "confidence":sum(s.score*len(s) for s in ss)/sum(len(s) for s in ss)})
    return result


def insert_pauses(waveform, rate, records, spans, *, skip_uncertain=False):
    """No samples are dropped or sped up; 3ms fades only at new silence edges."""
    import numpy as np
    audio = np.asarray(waveform,dtype=np.float32)
    if audio.ndim != 1 or not audio.size or not np.isfinite(audio).all() or rate < 8000:
        raise ValueError("停顿处理收到无效音频。")
    edits, skipped, cursor = [], [], 0
    # Prevalidate ALL boundaries before touching any sample.
    for record, following in zip(records, records[1:]):
        left, right = spans[record["last_word"]], spans[following["first_word"]]
        values = [left["start"],left["end"],right["start"],right["end"],left["confidence"],right["confidence"]]
        if (not all(math.isfinite(v) for v in values) or min(left["confidence"],right["confidence"]) < .25
                or not 0 <= left["start"] < left["end"] <= right["start"] < right["end"] <= len(audio)/rate+.04):
            if skip_uncertain:
                skipped.append({"punctuation_after":record["text"],"reason":"low_confidence_or_invalid_alignment"})
                continue
            raise ValueError("标点前后声音定位可信度不足；已保留完整原音，未按字数猜测或截断声音。")
        lo, hi = round(left["end"]*rate), min(len(audio),round(right["start"]*rate))
        window = max(1, round(.005*rate))
        # Select the lowest energy location INSIDE the measured interword gap.
        if hi-lo >= window:
            energy = np.convolve(audio[lo:hi].astype(np.float64)**2, np.ones(window)/window, mode="valid")
            cut = lo+int(energy.argmin())+window//2
        else:
            cut = (lo+hi)//2
        cut = min(len(audio)-1,max(1,cut))
        if cut <= cursor:
            if skip_uncertain:
                skipped.append({"punctuation_after":record["text"],"reason":"non_monotonic_boundary"})
                continue
            raise ValueError("停顿边界顺序不一致；未修改原始音频。")
        # Count only acoustically quiet time, never the entire alignment gap.
        threshold = max(.001, float(np.sqrt(np.mean(audio.astype(np.float64)**2)))*.10)
        hop = max(1,round(.005*rate))
        a, b = cut, cut
        while a-hop >= lo and np.sqrt(np.mean(audio[a-hop:a].astype(np.float64)**2)) <= threshold:
            a -= hop
        while b+hop <= hi and np.sqrt(np.mean(audio[b:b+hop].astype(np.float64)**2)) <= threshold:
            b += hop
        existing = (b-a)/rate
        added = max(0,round((record["minimum_seconds"]-existing)*rate))
        edits.append({"source_sample":cut, "added_samples":added,"existing_quiet_seconds":existing,
                      "minimum_seconds":record["minimum_seconds"],"confidence":min(left["confidence"],right["confidence"]),
                      "punctuation_after":record["text"]})
        cursor = cut
    parts, cursor, added = [], 0, 0
    for index, edit in enumerate(edits):
        cut, count = edit["source_sample"], edit["added_samples"]
        part = audio[cursor:cut].copy()
        fade = min(round(.003*rate),len(part)//2)
        if index and fade:
            # Start fade is needed only when previous boundary inserted silence.
            if edits[index-1]["added_samples"]:
                part[:fade] *= np.linspace(0,1,fade,dtype=np.float32)
        if count and fade:
            part[-fade:] *= np.linspace(1,0,fade,dtype=np.float32)
        parts.extend((part,np.zeros(count,dtype=np.float32)))
        edit["output_sample"] = cut+added
        added += count
        cursor = cut
    tail = audio[cursor:].copy()
    fade = min(round(.003*rate),len(tail)//2)
    if edits and edits[-1]["added_samples"] and fade:
        tail[:fade] *= np.linspace(0,1,fade,dtype=np.float32)
    parts.append(tail)
    result = np.concatenate(parts)
    assert len(result) == len(audio)+added
    return result, {"policy":POLICY,"boundaries":edits,"added_seconds":added/rate,
                    "source_samples":len(audio),"output_samples":len(result),
                    "skipped_boundaries":skipped,"pause_completion":"partial" if skipped else "complete",
                    "model_calls_for_speech":0,"boundary_fade_ms":3,"listening":"pending"}


def repair_file(source, target, text, language):
    records = phrases(text)
    if len(records) < 2:
        # No internal punctuation boundary; no alignment model download necessary.
        return None
    import soundfile as sf
    audio, rate = sf.read(str(source),dtype="float32")
    words, records = alignment_words(records,language)
    spans = acoustic_alignment(audio,rate,words)
    repaired, report = insert_pauses(audio,rate,records,spans,skip_uncertain=True)
    report["alignment_words"] = spans
    sf.write(str(target),repaired,rate,subtype="PCM_16")
    return report
