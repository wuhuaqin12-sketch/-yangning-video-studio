"""Independent preview host; does not import or change the installed Studio."""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def usable_tools(directory):
    suffix = ".exe" if os.name == "nt" else ""
    for name in ("ffmpeg", "ffprobe"):
        binary = Path(directory) / (name + suffix)
        if not binary.is_file():
            return False
        try:
            result = subprocess.run([str(binary), "-version"], capture_output=True, timeout=15)
            if result.returncode or name.encode() not in result.stdout.lower():
                return False
        except (OSError, subprocess.TimeoutExpired):
            return False
    return True


def find_media_tools():
    candidates = [Path(__file__).parent / "tools", Path(__file__).parent / "tools" / "bin"]
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Microsoft" / "WinGet" / "Packages"
        if base.is_dir():
            for package in base.glob("Gyan.FFmpeg*"):
                candidates.extend(path.parent for path in package.rglob("ffmpeg.exe"))
    for name in ("ffmpeg", "ffprobe"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found).parent)
    for directory in candidates:
        if usable_tools(directory):
            return directory
    return None


def ensure_media_tools():
    found = find_media_tools()
    if found is None and os.name == "nt":
        winget = shutil.which("winget")
        if winget:
            print("Preparing FFmpeg for this standalone preview...", flush=True)
            result = subprocess.run([
                winget, "install", "--exact", "--id", "Gyan.FFmpeg", "--source", "winget",
                "--scope", "user", "--accept-package-agreements", "--accept-source-agreements", "--silent",
            ])
            if result.returncode:
                raise RuntimeError("FFmpeg preparation failed. Keep this window open and share the error text, without any tokens.")
            found = find_media_tools()
    if found is None:
        raise RuntimeError("No working FFmpeg/FFprobe pair found. No changes were made to the installed Studio.")
    os.environ["PATH"] = str(found) + os.pathsep + os.environ.get("PATH", "")
    return found


def main():
    if sys.version_info < (3, 11):
        raise RuntimeError("This preview requires Python 3.11 or newer; Python 3.12 is recommended.")
    ensure_media_tools()
    if "--health-check" in sys.argv:
        import cloud_voice_core, kaggle_voice, voice_workflows, voice_adjust, cloud_voice_update
        print("Independent voice modules and media checks passed.")
        return
    if "--setup-only" in sys.argv:
        print("Standalone media tools check passed.")
        return
    import tkinter as tk
    from tkinter import ttk
    from types import SimpleNamespace

    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "YangNingCloudVoicePreview"
    os.environ["YANGNING_CLOUD_DATA_DIR"] = str(base)
    os.environ["YANGNING_CLOUD_CREDENTIAL_SERVICE"] = "YangNingStudio-Kaggle-Preview"
    from kaggle_voice import open_kaggle_voice
    from cloud_voice_update import open_update_window, acknowledge_boot
    from cloud_voice_version import VERSION

    root = tk.Tk()
    root.title("杨宁云端语音 · 独立试用")
    root.geometry("700x370")
    output = Path.home() / "Videos" / "YangNingCloudPreviewOutputs"
    app = SimpleNamespace(root=root, v={
        "video": tk.StringVar(), "audio": tk.StringVar(), "output": tk.StringVar(value=str(output)),
        "target_srt": tk.StringVar(), "speed": tk.StringVar(value="1.0"), "trim": tk.BooleanVar(value=False),
    }, auto_cut=tk.BooleanVar(value=False))
    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="杨宁云端语音克隆 · "+VERSION, font=("Microsoft YaHei UI", 17, "bold")).pack(anchor="w")
    def open_voice():
        open_kaggle_voice(app)
        acknowledge_boot(Path(__file__).resolve().parent.parent)
    app.check_updates=lambda:open_update_window(app)
    actions=ttk.Frame(frame);actions.pack(fill="x",pady=8)
    ttk.Button(actions, text="打开语音克隆", command=open_voice).pack(side="left")
    ttk.Button(actions,text="检查更新",command=app.check_updates).pack(side="left",padx=10)
    ttk.Label(frame, text="最近生成的WAV音频").pack(anchor="w")
    ttk.Entry(frame, textvariable=app.v["audio"]).pack(fill="x", pady=4)
    root.after(200, open_voice)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR:", exc, flush=True)
        raise SystemExit(1)
