"""Voice 1626 segment-based synthesis and localized replacement.

Requires voxcpm, soundfile and numpy in the voice Python environment.
"""
import argparse
import json
from pathlib import Path


def synthesize(payload, output, replace_index=None):
    from voxcpm import VoxCPM
    import numpy as np
    import soundfile as sf
    from voice_1626 import split_script
    ref = Path(payload["voice_reference_audio"])
    if not ref.is_file():
        raise FileNotFoundError("1626 reference audio not found")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
    rate = model.tts_model.sample_rate
    pieces = payload.get("segments") or split_script(payload["text"])
    if not pieces:
        raise ValueError("没有可朗读文本")
    folder = output.with_suffix("")
    folder = folder.with_name(folder.name + "_segments")
    folder.mkdir(parents=True, exist_ok=True)
    if replace_index is not None and not 0 <= replace_index < len(pieces):
        raise ValueError("无效的替换片段序号")
    indices = [replace_index] if replace_index is not None else range(len(pieces))
    for index in indices:
        print(f"Generating segment {index+1}/{len(pieces)}", flush=True)
        wav = model.generate(
            text=f"({payload['instructions'].strip()}){pieces[index]}",
            reference_wav_path=str(ref),
            cfg_value=2.0,
            inference_timesteps=10,
            seed=42 + index,
        )
        segment = np.asarray(wav, dtype=np.float32).reshape(-1)
        if segment.size == 0:
            raise RuntimeError("生成了空音频片段")
        # Write replacement atomically, retaining the original if synthesis fails.
        temp = folder / f"{index+1:05d}.pending.wav"
        sf.write(str(temp), segment, rate)
        temp.replace(folder / f"{index+1:05d}.wav")
    audio = []
    fade_samples = int(rate * 0.035)
    for index in range(len(pieces)):
        file = folder / f"{index+1:05d}.wav"
        if not file.is_file():
            raise FileNotFoundError(f"缺少音频片段 {index+1}")
        segment, sr = sf.read(str(file), dtype="float32")
        if sr != rate:
            raise ValueError("音频片段采样率不一致")
        if segment.ndim > 1:
            segment = segment.mean(axis=1)
        if not len(audio):
            audio = [segment]
            continue
        previous = audio[-1]
        # Crossfade only when both segments have safe boundary samples.
        n = min(fade_samples, len(previous)//4, len(segment)//4)
        if n > 0:
            ramp = np.linspace(0, 1, n, endpoint=True, dtype=np.float32)
            audio[-1] = previous[:-n]
            audio.append(previous[-n:] * (1-ramp) + segment[:n] * ramp)
            audio.append(segment[n:])
        else:
            audio.append(segment)
    result = np.concatenate(audio)
    pending = output.with_name(output.stem + ".pending.wav")
    sf.write(str(pending), result, rate)
    pending.replace(output)
    manifest = {
        "segments": pieces,
        "output": str(output.resolve()),
        "reference_audio": payload["voice_reference_audio"],
        "language": payload["language"],
        "instructions": payload["instructions"],
        "speed": payload["speed"],
    }
    output.with_suffix(".voice.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--replace-index", type=int)
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    synthesize(request, args.output, args.replace_index)


if __name__ == "__main__":
    main()
