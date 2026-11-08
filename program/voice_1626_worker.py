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
    from voice_1626 import split_script
    ref = Path(payload["voice_reference_audio"])
    if not ref.is_file():
        raise FileNotFoundError("1626 reference audio not found")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
    # VoxCPM2 accepts inline text control while the reference_wav_path
    # remains the ONLY timbre input. No other style/template audio is passed.
    instructions = payload["instructions"].strip()
    pieces = split_script(payload["text"])
    if not pieces:
        raise ValueError("文稿没有可朗读内容")
    audio_parts = []
    sample_rate = model.tts_model.sample_rate
    for index, piece in enumerate(pieces, 1):
        print(f"Generating segment {index}/{len(pieces)}", flush=True)
        # Instructions are best-effort; actual model behavior requires validation.
        wav = model.generate(
            text=f"({instructions}){piece}",
            reference_wav_path=str(ref),
            cfg_value=2.0,
            inference_timesteps=10,
            seed=42 + index,
        )
        audio_parts.append(np.asarray(wav).reshape(-1))
        if index < len(pieces):
            audio_parts.append(np.zeros(int(sample_rate * 0.3), dtype=np.float32))
    sf.write(str(output), np.concatenate(audio_parts), sample_rate)
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
