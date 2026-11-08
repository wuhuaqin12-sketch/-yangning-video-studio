# 1626 voice synthesis setup (experimental)

The voice UI is under **更多设置 → AI语音克隆 · 1626**. Its single
speaker-reference file is the teacher's authorized 1626 recording. No
prosody-template recordings are used.

## Engine

Selected engine: [VoxCPM2](https://github.com/OpenBMB/VoxCPM) (Apache-2.0).
It supports Japanese, English, French, German, Indonesian, and Cantonese, plus
instruction-controlled cloning using `reference_wav_path`.

This is an **optional** heavyweight engine. The normal desktop ZIP and its
200 MB update limit do not include model weights or PyTorch.

On Windows, install Python 3.11 or 3.12, then in PowerShell:

```powershell
py -3.11 -m venv "$env:LOCALAPPDATA\YangNingStudio\voice_env"
& "$env:LOCALAPPDATA\YangNingStudio\voice_env\Scripts\python.exe" -m pip install --upgrade pip
& "$env:LOCALAPPDATA\YangNingStudio\voice_env\Scripts\python.exe" -m pip install voxcpm soundfile
```

In the voice window, select that environment's `python.exe`. First
synthesis downloads VoxCPM2 weights. This requires a suitable machine;
the official model indicates around 8 GB GPU VRAM for GPU inference.
The worker has a one-hour timeout and returns actionable errors if the
engine is unavailable. Audio is written only when synthesis succeeds.

## Known limits / release gate

- No actual 1626 reference audio is included in the repository.
- Natural-language style guidance is **best effort**, not a guaranteed
  deterministic control; the source voice can still drift.
- VoxCPM2 detects language from text. The UI language selector currently
  validates the intended language but is not a language-locking parameter.
- UI speed is not yet enforced as a post-processing ratio.
- No Windows GPU model download, 1626 timbre comparison, six-language
  listening QA, or end-to-end packaging verification has been performed.
- **Do not merge or publish this feature as production-ready until these
  acceptance checks pass.** Existing stable 12.10 remains unchanged.
