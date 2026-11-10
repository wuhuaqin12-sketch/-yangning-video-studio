"""Embedded in a private Kaggle notebook. Heavy imports occur only in run()."""
import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

MODEL_ID = "openbmb/VoxCPM2"
PACKAGE_VERSION = "2.0.3"
REFERENCE_SHA256 = "9be7f58bb98d61e33a3255a7fd963eda850219f8c8596e716675c078a2d0f0f6"
PROFILES = {
    "日语": {
        "style": "Warm, gentle Japanese narration, effortless and relaxed delivery, smoothly connected phrases, subtle intonation",
        "tempo": 1.0,
        "basis": "Natural model speed; template rhythm summary only, no automatic slowdown",
    },
    "英语": {
        "style": "Calm, natural English narration, warm and gentle, smoothly connected phrases, subtle intonation and natural pauses",
        "tempo": 1.0,
        "basis": "Natural model speed; optional template acoustic-summary instructions",
    },
    "法语": {
        "style": "Natural French narration, calm and flowing, gentle emphasis, subtle intonation and natural pauses",
        "tempo": 1.0,
        "basis": "Natural speed with French phrasing; English-template rhythm summary optional",
    },
    "德语": {
        "style": "Natural German narration, calm and flowing, gentle emphasis, subtle intonation and natural pauses",
        "tempo": 1.0,
        "basis": "Natural speed with German phrasing; English-template rhythm summary optional",
    },
    "印尼语": {
        "style": "Natural Indonesian narration, calm and flowing, gentle emphasis, subtle intonation and natural pauses",
        "tempo": 1.0,
        "basis": "Provisional natural delivery; no additional slowdown confirmed",
    },
    "粤语": {
        "style": "Natural Cantonese narration, relaxed and flowing delivery, gentle emphasis, subtle intonation and natural pauses",
        "tempo": 1.0,
        "basis": "Provisional natural Cantonese delivery; audition pending",
    },
}


def profile_for(language, tempo=None):
    if language not in PROFILES:
        raise ValueError("请选择支持的配音语言。")
    profile = copy.deepcopy(PROFILES[language])
    if tempo is not None:
        tempo = float(tempo)
        if not math.isfinite(tempo) or not 0.5 <= tempo <= 2.0:
            raise ValueError("倍数须在0.5到2.0之间。")
        profile["tempo"] = tempo
    return profile


def split_script(text, target_chars=900):
    """Keep complete sentences/paragraphs together. Never split at a comma."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    result = []
    for paragraph in paragraphs:
        if len(paragraph) <= target_chars:
            result.append(paragraph)
            continue
        boundaries = list(re.finditer(r"[。！？!?](?:[」』”\"])?\s*|\.(?:[”\"])?\s+(?=[A-Z“\"])", paragraph))
        sentences, start = [], 0
        for match in boundaries:
            prefix = paragraph[start:match.end()].strip()
            if re.search(r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr)\.$", prefix):
                continue
            sentences.append(prefix)
            start = match.end()
        if paragraph[start:].strip():
            sentences.append(paragraph[start:].strip())
        block = ""
        for sentence in sentences or [paragraph]:
            if len(sentence) > 3000:
                raise ValueError("有一个超过3000字的连续语句。请按完整句意添加句号或段落；正文不会被截断。")
            if block and len(block) + len(sentence) > target_chars:
                result.append(block)
                block = ""
            block = (block + " " + sentence).strip()
        if block:
            result.append(block)
    if not result:
        raise ValueError("朗读正文为空。")
    return result


def filter_graph(tempo, gain_db=0.0, light_denoise=True):
    tempo = float(tempo)
    if not math.isfinite(tempo) or not 0.5 <= tempo <= 2.0:
        raise ValueError("倍数须在0.5到2.0之间。")
    chain = "afftdn=nr=6:nf=-55:tn=1:gs=8" if light_denoise else "anull"
    if tempo != 1.0:
        chain += (
            f",rubberband=tempo={tempo}:pitch=1:formant=preserved:"
            "pitchq=quality:transients=crisp:detector=soft:phase=laminar"
        )
    if gain_db:
        chain += f",volume={gain_db}dB"
        if gain_db > 0:
            chain += ",alimiter=limit=0.95:level=0:latency=1"
    return chain


def check_audio_tools(tempo):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("云端缺少 FFmpeg，无法按确认标准进行降噪及保音高处理。")
    available = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, check=True).stdout
    required = ["afftdn"] + (["rubberband"] if tempo != 1.0 else [])
    if any(not re.search(r"\b" + name + r"\b", available) for name in required):
        raise RuntimeError("云端 FFmpeg 缺少所需音频滤镜；保留原始 WAV，未用其他变速方式替代。")
    return ffmpeg


def ensure_audio_tools(tempo):
    try:
        return check_audio_tools(tempo)
    except RuntimeError:
        if getattr(os, "geteuid", lambda: -1)() != 0 or not shutil.which("apt-get"):
            raise
        # Repair the cloud-only dependency before downloading/initializing the model.
        subprocess.run(["apt-get", "update", "-qq"], check=True, capture_output=True, timeout=300)
        subprocess.run(["apt-get", "install", "-y", "ffmpeg"], check=True, capture_output=True, timeout=300)
        return check_audio_tools(tempo)


def process_audio(raw_path, final_path, tempo, gain_db=0.0, light_denoise=True):
    ffmpeg = check_audio_tools(tempo)
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw_path),
        "-af", filter_graph(tempo,gain_db,light_denoise), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(final_path),
    ], check=True, capture_output=True)
    with wave.open(str(raw_path), "rb") as source, wave.open(str(final_path), "rb") as final:
        before = source.getnframes() / source.getframerate()
        after = final.getnframes() / final.getframerate()
        if (final.getnchannels(), final.getsampwidth(), final.getframerate()) != (1, 2, 48000):
            raise RuntimeError("输出不是48kHz单声道PCM16 WAV。")
    if abs(after - before / tempo) > max(0.08, before / tempo * 0.002):
        raise RuntimeError("处理后的时长不符合整段保音高变速，未交付该结果。")
    return {"raw_seconds": before, "final_seconds": after, "filter": filter_graph(tempo,gain_db,light_denoise)}


def request_fingerprint(request):
    fields=("text","reading_text","units","language","seed","tempo","postprocess","delivery_instruction","prosody_reference","pronunciation")
    data={key:request.get(key) for key in fields}
    data.update(reference=REFERENCE_SHA256,model=MODEL_ID,package=PACKAGE_VERSION,cfg=2.0,steps=10,max_len=4096,base_profile=profile_for(request["language"],request.get("tempo")),normalize=False,denoise=False,retry=False)
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def atomic_json(path,value):
    path=Path(path);pending=path.with_suffix(path.suffix+".tmp")
    pending.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8");pending.replace(path)


def checkpoint_parts(manifest_path,request):
    import numpy as np
    path=Path(manifest_path)
    record=json.loads(path.read_text(encoding="utf-8"))
    blocks=[unit["reading_text"] for unit in request["units"]] if request.get("units") else split_script(request.get("reading_text",request["text"]))
    if (record.get("fingerprint")!=request_fingerprint(request) or record.get("total")!=len(blocks)
            or not isinstance(record.get("rate"),int) or not 8000<=record["rate"]<=96000):
        raise ValueError("断点记录与原文、音色或生成参数不一致。")
    valid={}
    for piece in record.get("pieces",[]):
        index=piece.get("index")
        if not isinstance(index,int) or not 0<=index<len(blocks) or index in valid: raise ValueError("断点段号无效。")
        relative=Path(piece.get("file",""))
        if relative.is_absolute() or ".." in relative.parts or relative.suffix!=".npz": raise ValueError("断点文件路径无效。")
        audio_path=path.parent/relative
        if hashlib.sha256(audio_path.read_bytes()).hexdigest()!=piece.get("sha256"): raise ValueError("断点音频校验不一致。")
        if hashlib.sha256(blocks[index].encode()).hexdigest()!=piece.get("text_sha256"): raise ValueError("断点文字校验不一致。")
        with np.load(audio_path,allow_pickle=False) as data:
            audio=data["audio"]
            if audio.ndim!=1 or not 0<audio.size<=record["rate"]*1200 or not np.isfinite(audio).all(): raise ValueError("断点音频无效。")
        valid[index]=(piece,audio_path)
    return record,valid


def run(request):
    import numpy as np
    import soundfile as sf
    import torch
    from huggingface_hub import snapshot_download
    from voxcpm import VoxCPM

    print("YANGNING_STAGE=preflight", flush=True)
    if not torch.cuda.is_available():
        raise RuntimeError("此Kaggle作业没有分配到GPU；请检查账号GPU权限及剩余额度。")
    candidates = [p for p in Path("/kaggle/input").rglob("*") if p.is_file() and p.name in ("1626_reference.wav", "1626_reference.wav.wav")]
    reference = next((p for p in candidates if hashlib.sha256(p.read_bytes()).hexdigest() == REFERENCE_SHA256), Path(request["reference_path"]))
    if not reference.is_file():
        raise FileNotFoundError("私有数据集中找不到已配置的老师原声参考文件。")
    reference_hash = hashlib.sha256(reference.read_bytes()).hexdigest()
    if reference_hash != REFERENCE_SHA256:
        raise ValueError("参考文件与已确认的老师原声不一致。请上传原始10秒参考文件，仅改文件名即可，不要重新编码。")
    profile = profile_for(request["language"], request.get("tempo"))
    prosody = request.get("prosody_reference")
    if prosody:
        if prosody.get("method") != "aggregate_acoustic_summary_to_text" or prosody.get("template_waveform_sent_to_model") is not False:
            raise ValueError("语气模板必须只提供节奏摘要，不能作为音色或续写音频。")
        profile["style"] += ", " + prosody["instruction"]
    if request.get("delivery_instruction"):
        profile["style"] += ", " + request["delivery_instruction"]
    spoken_text = request.get("reading_text", request["text"])
    blocks = [unit["reading_text"] for unit in request["units"]] if request.get("units") else split_script(spoken_text)
    ensure_audio_tools(profile["tempo"])
    output_dir = Path(request.get("output_dir", "/kaggle/working"))
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path, final_path = output_dir / "yangning_raw.wav", output_dir / "yangning_final.wav"
    (output_dir / "script.txt").write_text(request["text"], encoding="utf-8")
    (output_dir / "reading_text.txt").write_text(spoken_text, encoding="utf-8")
    if request.get("pronunciation"):
        (output_dir / "pronunciation_plan.json").write_text(json.dumps(request["pronunciation"],ensure_ascii=False,indent=2),encoding="utf-8")

    # Cache weights outside /kaggle/working so they are not saved as job outputs.
    print("YANGNING_STAGE=model_download", flush=True)
    snapshot = Path(snapshot_download(MODEL_ID, cache_dir="/tmp/yangning_hf_cache", **({"revision":request["model_revision"]} if request.get("model_revision") else {})))
    config = json.loads((snapshot / "config.json").read_text(encoding="utf-8"))
    dtype = config.get("dtype", "bfloat16")
    if dtype in ("bfloat16", "bf16") and not torch.cuda.is_bf16_supported():
        dtype = "float32"
    config["dtype"] = dtype
    runtime = Path(tempfile.mkdtemp(prefix="yangning_voxcpm2_"))
    for entry in snapshot.iterdir():
        if entry.name != "config.json":
            (runtime / entry.name).symlink_to(entry, target_is_directory=entry.is_dir())
    (runtime / "config.json").write_text(json.dumps(config), encoding="utf-8")
    model = VoxCPM.from_pretrained(str(runtime), load_denoiser=False, optimize=False, device="cuda")
    rate = int(model.tts_model.sample_rate)
    seeds, peaks, lengths = [], [], []
    folder=output_dir/"checkpoints";folder.mkdir(exist_ok=True)
    checkpoint={"version":1,"job_id":request["job_id"],"fingerprint":request_fingerprint(request),"snapshot_revision":snapshot.name,
                "rate":rate,"model_dtype":dtype,"total":len(blocks),"pieces":[]}
    available={}
    if request.get("resume_checkpoint_job_id"):
        for candidate in Path("/kaggle/input").rglob("checkpoint_manifest.json"):
            record=json.loads(candidate.read_text(encoding="utf-8"))
            if record.get("job_id")==request["resume_checkpoint_job_id"]:
                record,available=checkpoint_parts(candidate,request)
                if record["snapshot_revision"]!=snapshot.name or record["rate"]!=rate or record.get("model_dtype")!=dtype: raise ValueError("断点模型快照或采样率不一致。")
                break
        if not available: raise ValueError("没有取得可校验的已完成段落；不会静默从头生成。")
    atomic_json(output_dir/"checkpoint_manifest.json",checkpoint)
    base_seed = int(request.get("seed", 16261109))
    print("YANGNING_STAGE=generation", flush=True)
    for index, block in enumerate(blocks):
        seed = base_seed + index if base_seed >= 0 else None
        if seed is not None:
            torch.manual_seed(seed);torch.cuda.manual_seed_all(seed);np.random.seed(seed % (2**32))
        target=folder/f"part_{index:05d}.npz"
        if index in available:
            old,source=available[index]
            shutil.copy2(source,target)
            with np.load(target,allow_pickle=False) as data: audio=data["audio"].astype(np.float32)
            print(f"复用已完成段落 {index+1}",flush=True)
        else:
            audio = np.asarray(model.generate(
                text=f"({profile['style']}){block}", reference_wav_path=str(reference),
                prompt_wav_path=None, prompt_text=None, cfg_value=2.0, inference_timesteps=10,
                normalize=False, denoise=False, retry_badcase=False, max_len=4096,
            ), dtype=np.float32).reshape(-1)
            if not audio.size or not np.isfinite(audio).all(): raise RuntimeError(f"第{index+1}段没有返回有效音频。")
            pending=target.with_suffix(".tmp")
            with pending.open("wb") as stream: np.savez(stream,audio=audio)
            pending.replace(target)
        seeds.append(seed);peaks.append(float(np.max(np.abs(audio))));lengths.append(int(audio.size))
        checkpoint["pieces"].append({"index":index,"file":str(target.relative_to(output_dir)),
                                     "sha256":hashlib.sha256(target.read_bytes()).hexdigest(),"text_sha256":hashlib.sha256(block.encode()).hexdigest()})
        atomic_json(output_dir/"checkpoint_manifest.json",checkpoint)
        print(f"已生成 {index+1}/{len(blocks)} 个完整语义段",flush=True)
    peak=max(peaks);gain=.99/peak if peak>=1 else 1.0
    # Stream one semantic unit at a time; preserve all samples and pauses.
    with wave.open(str(raw_path),"wb") as destination:
        destination.setparams((1,2,rate,0,"NONE","not compressed"))
        for piece in checkpoint["pieces"]:
            with np.load(output_dir/piece["file"],allow_pickle=False) as data:
                values=np.rint(data["audio"]*gain*32768).clip(-32768,32767).astype("<i2")
                destination.writeframes(values.tobytes())
    recipe = {
        "job_id": request["job_id"], "purpose":request.get("purpose","full"), "model": MODEL_ID, "package": f"voxcpm=={PACKAGE_VERSION}", "snapshot_revision": snapshot.name,
        "language": request["language"], "reference_sha256": reference_hash,
        "template_audio_used": False, "template_prosody_alignment": "not_implemented",
        "prosody_reference": prosody, "template_selection": request.get("template_selection"),
        "pronunciation": request.get("pronunciation"),
        "delivery_instruction": request.get("delivery_instruction", ""),
        "postprocess": request.get("postprocess", {"gain_db":0.0,"light_denoise":True}),
        "style_control": "text_instruction", "profile": profile, "seed_per_block": seeds,
        "cfg_value": 2.0, "inference_timesteps": 10, "max_len": 4096,
        "normalize": False, "model_denoise": False, "retry_badcase": False,
        "device": torch.cuda.get_device_name(0), "model_dtype": dtype,
        "blocks": blocks, "block_peaks": peaks, "headroom_gain": gain,
        "silence_trimmed": False, "pitch_ratio": 1.0, "tempo_applications": 1,
        "review": {name: "待听检" for name in ("音色", "读音与全文完整性", "语感", "重点", "问句", "停顿", "声音")},
    }
    try:
        print("YANGNING_STAGE=postprocess", flush=True)
        post = request.get("postprocess",{})
        gain_db=float(post.get("gain_db",0.0))
        if not math.isfinite(gain_db) or not -12 <= gain_db <= 6:
            raise ValueError("音量设置无效。")
        recipe.update(process_audio(raw_path, final_path, profile["tempo"],gain_db,post.get("light_denoise",True)))
        position=0
        segments=[]
        scale=recipe["final_seconds"]/(sum(lengths)/rate)
        units=request.get("units") or [{"text":block,"reading_text":block} for block in blocks]
        for unit,length in zip(units,lengths):
            segments.append({"start":position/rate*scale,"end":(position+length)/rate*scale,"text":unit["text"]})
            position+=length
        atomic_json(output_dir/"segments.json",{"audio_sha256":hashlib.sha256(final_path.read_bytes()).hexdigest(),
                    "timing":"generated_units" if profile["tempo"]==1 else "estimated_after_tempo", "segments":segments})
        recipe["resumed_segments"]=len(available)
        recipe["status"] = "generated_pending_review"
    except Exception as exc:
        recipe.update(status="postprocess_failed", error=str(exc))
        raise
    finally:
        (output_dir / "voice_recipe.json").write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.rmtree(runtime, ignore_errors=True)
    print(f"WAV={final_path}", flush=True)

