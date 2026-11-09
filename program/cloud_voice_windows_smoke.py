"""Windows-only GUI/credential smoke checks, using temporary nonsensitive data."""
import os
import sys
import subprocess
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace


def main():
    if os.name != "nt":
        raise SystemExit("This check must run on Windows.")
    if "--package-dir" in sys.argv:
        folder = Path(sys.argv[sys.argv.index("--package-dir") + 1]).resolve()
        if not (folder / "kaggle_voice.py").is_file():
            raise ValueError("The extracted preview program directory is missing.")
        sys.path.insert(0, str(folder))
    subprocess.run([sys.executable, "-m", "kaggle", "--version"], check=True, capture_output=True)
    service = "YangNingCloudVoice-CI-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory() as directory:
        os.environ["YANGNING_CLOUD_DATA_DIR"] = directory
        os.environ["YANGNING_CLOUD_CREDENTIAL_SERVICE"] = service
        import tkinter as tk
        from tkinter import ttk
        from kaggle_voice import _vault, open_kaggle_voice
        from cloud_voice_preview import ensure_media_tools

        vault = _vault()
        try:
            vault.set_password(service, "test-user", "temporary-ci-value-not-a-real-token")
            assert vault.get_password(service, "test-user") == "temporary-ci-value-not-a-real-token"
        finally:
            try:
                vault.delete_password(service, "test-user")
            except Exception:
                pass
        assert not list(Path(directory).rglob("*.json")), "Credential check must not create plaintext JSON."
        ensure_media_tools()
        root = tk.Tk()
        root.withdraw()
        app = SimpleNamespace(root=root, v={
            "video": tk.StringVar(), "audio": tk.StringVar(), "output": tk.StringVar(value=directory),
            "speed": tk.StringVar(value="1.0"), "target_srt": tk.StringVar(), "trim": tk.BooleanVar(value=False),
        }, auto_cut=tk.BooleanVar(value=False))
        try:
            open_kaggle_voice(app)
            root.update()
            window = app._cloud_voice_window
            assert window.winfo_exists()
            def descendants(widget):
                result = []
                for child in widget.winfo_children():
                    result.append(child)
                    result.extend(descendants(child))
                return result
            widgets = descendants(window)
            labels = [str(w.cget("text")) for w in widgets if isinstance(w, ttk.Button)]
            assert "生成音频" in labels and "恢复最近任务" in labels
            assert "预览实际朗读稿" in labels and "编辑术语读音表" in labels
            next(w for w in widgets if isinstance(w,ttk.Button) and w.cget("text") == "编辑术语读音表").invoke()
            root.update()
            dictionary_window = next(w for w in window.winfo_children() if isinstance(w,tk.Toplevel) and w.title() == "日语术语读音表")
            editors = [w for w in dictionary_window.winfo_children() if isinstance(w,tk.Text)]
            assert "金剛経=こんごうきょう" in editors[0].get("1.0","end")
            editors[1].insert("1.0","聞性=もんしょう")
            next(w for w in dictionary_window.winfo_children() if isinstance(w,ttk.Button) and w.cget("text") == "保存读音表").invoke()
            root.update()
            import json
            saved = json.loads((Path(directory)/"kaggle_voice_settings.json").read_text(encoding="utf-8"))
            assert saved["japanese_pronunciation_overrides"]["聞性"] == "もんしょう"
            # Audio correction is separate from ordinary generation; no video controls.
            correction = next(w for w in widgets if isinstance(w, ttk.LabelFrame) and w.cget("text") == "原音频与替换句段")
            assert correction.winfo_manager() == ""
            by_text = {str(w.cget("text")): w for w in widgets if isinstance(w, ttk.Radiobutton)}
            assert by_text["生成新音频"].instate(["selected"])
            assert not any("视频" in str(w.cget("text")) or "成片" in str(w.cget("text")) for w in widgets if isinstance(w, (ttk.Button, ttk.Radiobutton)))
            by_text["局部改读音并接回原音频"].invoke()
            root.update()
            assert correction.winfo_manager() == "pack"
            assert "重生成句段并连接完整音频" in [str(w.cget("text")) for w in widgets if isinstance(w, ttk.Button)]
            by_text["修改全文后重新生成"].invoke()
            root.update()
            assert correction.winfo_manager() == ""
            assert "全文重新生成" in [str(w.cget("text")) for w in widgets if isinstance(w, ttk.Button)]
            by_text["生成新音频"].invoke()
            root.update()
            assert correction.winfo_manager() == ""
            assert "生成音频" in [str(w.cget("text")) for w in widgets if isinstance(w, ttk.Button)]
            speeds = [w for w in widgets if isinstance(w, ttk.Combobox) and "0.84" in tuple(w.cget("values"))]
            assert len(speeds) == 1
            speeds[0].set("1.1")
            assert speeds[0].get() == "1.1"
            open_kaggle_voice(app)
            assert app._cloud_voice_window is window, "Repeated open should reuse one window."
            root.update()
        finally:
            root.destroy()
    print("Windows preview GUI, media tools and credential-vault checks passed. No Kaggle account used.")


if __name__ == "__main__":
    main()
