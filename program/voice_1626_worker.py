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
    ref = Path(payload["voice_reference_audio"])
    if not ref.is_file():
        raise FileNotFoundError("1626 reference audio not found")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
    # VoxCPM2 accepts inline text control while the reference_wav_path
    # remains the ONLY timbre input. No other style/template audio is passed.
    instructions = payload["instructions"].strip()
    text = f"({instructions}){payload['text']}"
    wav = model.generate(
        text=text,
        reference_wav_path=str(ref),
        cfg_value=2.0,
        inference_timesteps=10,
        seed=42,
    )
    sf.write(str(output), wav, model.tts_model.sample_rate)
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
