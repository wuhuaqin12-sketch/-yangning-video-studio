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
        callback_errors=[]
        root.report_callback_exception=lambda kind,value,trace:callback_errors.append(str(value))
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
            def on_main(widget):
                current = widget
                while current is not window:
                    if isinstance(current, tk.Toplevel):
                        return False
                    current = current.master
                return True
            main_labels = [str(w.cget("text")) for w in widgets if isinstance(w,ttk.Label) and on_main(w)]
            assert any(label.startswith("老师音色") for label in main_labels)
            assert not any("语气模板只提供" in label or "输出WAV音频" in label for label in main_labels)
            main_buttons = [str(w.cget("text")) for w in widgets if isinstance(w,ttk.Button) and on_main(w)]
            assert "生成音频" in main_buttons and "全文重新生成" not in main_buttons
            assert "详细调节" not in main_buttons
            engine_selector=next(w for w in widgets if isinstance(w,ttk.Combobox) and "本机生成" in tuple(w.cget("values")))
            assert engine_selector.get()=="云端生成", "Existing users must stay on cloud by default"
            engine_selector.set("本机生成");engine_selector.event_generate("<<ComboboxSelected>>");root.update()
            local_panel=next(w for w in widgets if isinstance(w,ttk.LabelFrame) and str(w.cget("text")).startswith("本机模型"))
            cloud_panel=next(w for w in widgets if isinstance(w,ttk.LabelFrame) and w.cget("text")=="云端连接Kaggle")
            assert local_panel.winfo_manager()=="pack" and cloud_panel.winfo_manager()==""
            engine_selector.set("云端生成");engine_selector.event_generate("<<ComboboxSelected>>");root.update()
            assert cloud_panel.winfo_manager()=="pack" and local_panel.winfo_manager()==""
            labels = [str(w.cget("text")) for w in widgets if isinstance(w, ttk.Button)]
            assert not any("1626" in str(w.cget("text")) for w in widgets if isinstance(w,(ttk.Label,ttk.Button,ttk.LabelFrame)))
            assert "生成音频" in labels and "恢复最近任务" in labels
            assert "检查更新" in labels
            assert "更多设置 ⋯" in labels and "音频微调" in labels
            for control in ("先预听约15秒","试听预听","按句段试听 / 修改","术语集中试听","续生成未完成段（已有断点时）","加入本语言模板库（以后自动选择）"):
                assert control in labels, control
            next(w for w in widgets if isinstance(w,ttk.Button) and w.cget("text")=="术语集中试听").invoke()
            root.update()
            term_window=next(w for w in window.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=="术语集中试听")
            assert any(isinstance(w,tk.Text) for w in descendants(term_window))
            term_window.destroy()
            more=next(w for w in window.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=="更多设置")
            assert more.state()=="withdrawn"
            notebook=next(w for w in more.winfo_children() if isinstance(w,ttk.Notebook))
            assert len(notebook.tabs())==4
            from unittest.mock import patch
            import time
            import cloud_voice_update
            fake={"available":False,"current":"0.5-preview.1","update":{"version":"0.5-preview.1","notes":"已通过检查"}}
            with patch.object(cloud_voice_update,"check_update",return_value=fake):
                next(w for w in widgets if isinstance(w,ttk.Button) and w.cget("text")=="检查更新").invoke()
                deadline=time.monotonic()+4
                while time.monotonic()<deadline:
                    root.update();time.sleep(.03)
                    update_window=getattr(app,"_cloud_update_window",None)
                    if update_window and any(isinstance(w,ttk.Label) and "已是当前渠道最新版" in str(w.cget("text")) for w in descendants(update_window)): break
                else: raise AssertionError("Update dialog did not finish checking")
                update_window.destroy()
            next(w for w in widgets if isinstance(w,ttk.Button) and w.cget("text")=="音频微调").invoke()
            root.update()
            adjustment=next(w for w in window.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=="音频微调 · 保留原版")
            assert any(isinstance(w,ttk.Button) and w.cget("text")=="识别指令并预览动作" for w in descendants(adjustment))
            adjustment.destroy()
            assert "预览实际朗读稿" in labels and "编辑术语读音表" in labels
            # All changes are selectable before generation and persist by language.
            next(w for w in widgets if isinstance(w,ttk.Button) and w.cget("text")=="更多设置 ⋯").invoke()
            root.update()
            assert more.state()=="normal"
            softer=next(w for w in widgets if isinstance(w,ttk.Checkbutton) and w.cget("text")=="更柔和")
            softer.invoke()
            next(w for w in descendants(more) if isinstance(w,ttk.Button) and w.cget("text")=="保存当前语言设置").invoke()
            import json
            preferences=json.loads((Path(directory)/"kaggle_voice_settings.json").read_text(encoding="utf-8"))
            assert "更柔和" in preferences["generation_by_language"]["日语"]["styles"]
            lang_combo=next(w for w in widgets if isinstance(w,ttk.Combobox) and "日语" in tuple(w.cget("values")))
            lang_combo.set("英语");lang_combo.event_generate("<<ComboboxSelected>>");root.update()
            assert not softer.instate(["selected"])
            lang_combo.set("日语");lang_combo.event_generate("<<ComboboxSelected>>");root.update()
            assert softer.instate(["selected"])
            template_selector=next(w for w in widgets if isinstance(w,ttk.Combobox) and "自动选择" in tuple(w.cget("values")))
            assert template_selector.get()=="自动选择"
            next(w for w in widgets if isinstance(w,ttk.Button) and w.cget("text")=="清除选择").invoke()
            root.update()
            assert template_selector.get()=="自然语气（无模板）"
            assert any(isinstance(w,ttk.Label) and "未使用音频模板" in str(w.cget("text")) for w in widgets)
            template_selector.set("自动选择");template_selector.event_generate("<<ComboboxSelected>>");root.update()
            more.withdraw()
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
            # Source change must invalidate stale subtitle/range associations.
            entries=[w for w in descendants(correction) if isinstance(w,ttk.Entry)]
            assert len(entries)==4
            entries[1].insert(0,"old-subtitles.srt")
            entries[2].insert(0,"2");entries[3].insert(0,"3")
            entries[0].delete(0,"end");entries[0].insert(0,"new-source.wav")
            root.update()
            assert entries[1].get()=="" and entries[2].get()=="" and entries[3].get()==""
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
            window.geometry("720x480");root.update()
            # Main action remains reachable through scrolling on a small laptop.
            main_canvas=next(w for w in widgets if isinstance(w,tk.Canvas) and w.winfo_toplevel() is window)
            main_canvas.yview_moveto(1);root.update()
            generate=next(w for w in widgets if isinstance(w,ttk.Button) and w.cget("text")=="生成音频")
            assert generate.winfo_rooty()>=main_canvas.winfo_rooty()
            assert generate.winfo_rooty()+generate.winfo_height()<=main_canvas.winfo_rooty()+main_canvas.winfo_height()+2
            # Local submission must bypass the Windows Kaggle vault entirely.
            import hashlib,wave
            import local_voice,kaggle_voice
            reference=Path(directory)/"teacher-fixture.wav"
            with wave.open(str(reference),"wb") as audio:
                audio.setparams((1,2,48000,0,"NONE","not compressed"));audio.writeframes(b'\x01\x00'*4800)
            engine_selector.set("本机生成");engine_selector.event_generate("<<ComboboxSelected>>");root.update()
            reference_entry=next(w for w in local_panel.winfo_children() if isinstance(w,ttk.Entry))
            reference_entry.delete(0,"end");reference_entry.insert(0,str(reference))
            script=next(w for w in widgets if isinstance(w,tk.Text) and on_main(w))
            script.delete("1.0","end");script.insert("1.0","金剛経。")
            routed=[]
            def local_run(record,emit):
                routed.append(json.loads(Path(record).read_text(encoding="utf-8")))
                emit(("local_ready","Local routing checked"))
            with patch.object(local_voice,"REFERENCE_SHA256",hashlib.sha256(reference.read_bytes()).hexdigest()),patch.object(kaggle_voice,"_vault",side_effect=AssertionError("Local must not request Kaggle credentials")),patch.object(kaggle_voice,"run_local_job",side_effect=local_run):
                generate.invoke()
                deadline=time.monotonic()+5
                while time.monotonic()<deadline and not routed:
                    root.update();time.sleep(.03)
                root.update()
                assert routed and routed[0]["execution"]=="local" and routed[0]["username"]=="local"
            open_kaggle_voice(app)
            assert app._cloud_voice_window is window, "Repeated open should reuse one window."
            root.update()
            assert not callback_errors, callback_errors
        finally:
            root.destroy()
    print("Windows preview GUI, media tools and credential-vault checks passed. No Kaggle account used.")


if __name__ == "__main__":
    main()
