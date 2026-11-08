"""VoxCPM2 synthesis worker, launched using a separately installed Python environment.

Install once: python -m pip install voxcpm soundfile
Model weights are downloaded by VoxCPM on first use; do not bundle in app updates.
"""
import argparse
import json
import sys
from pathlib import Path

def synthesize(payload, output):
    from voxcpm import VoxCPM
    import soundfile as sf
    import numpy as np
    from voice_1626 import split_script, build_srt_from_durations
    ref = Path(payload["voice_reference_audio"])
    if not ref.is_file():
        raise FileNotFoundError("1626 reference audio not found")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
    # VoxCPM2 accepts inline text control while the reference_wav_path
    # remains the ONLY timbre input. No other style/template audio is passed.
    instructions = payload["instructions"].strip()
    cues = payload.get("srt_cues")
    units = cues if cues else [payload["text"]]
    if not units or not any(str(u).strip() for u in units):
        raise ValueError("文稿没有可朗读内容")
    sample_rate = model.tts_model.sample_rate
    gap_seconds = 0.3
    audio_parts, cue_durations = [], []
    for cue_index, unit in enumerate(units, 1):
        subparts = split_script(unit)
        unit_audio = []
        for index, piece in enumerate(subparts, 1):
            print(f"Generating cue {cue_index}/{len(units)}, part {index}/{len(subparts)}", flush=True)
            wav = model.generate(
                text=f"({instructions}){piece}",
                reference_wav_path=str(ref),
                cfg_value=2.0,
                inference_timesteps=10,
                seed=42 + cue_index + index,
            )
            unit_audio.append(np.asarray(wav).reshape(-1))
            if index < len(subparts):
                unit_audio.append(np.zeros(int(sample_rate * gap_seconds), dtype=np.float32))
        if not unit_audio:
            raise ValueError(f"第{cue_index}条字幕为空")
        joined = np.concatenate(unit_audio)
        cue_durations.append(len(joined) / sample_rate)
        audio_parts.append(joined)
        if cue_index < len(units):
            audio_parts.append(np.zeros(int(sample_rate * gap_seconds), dtype=np.float32))
    sf.write(str(output), np.concatenate(audio_parts), sample_rate)
    if cues:
        new_srt = build_srt_from_durations(cues, cue_durations, gap_seconds)
        output.with_suffix(".srt").write_text(new_srt, encoding="utf-8-sig")
    return output

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--request", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    synthesize(request, args.output)

if __name__ == "__main__":
    main()
