import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

from cloud_voice_core import auth_env, build_notebook, prepare_job, run_job, script_from_text, state_from_output
from voice_clip_edit import command, export_edited_clip, patch_audio, preflight_edit, probe, read_frames, read_srt, remap_subtitles, tool, wav_info, write_srt
from voxcpm_kaggle_worker import REFERENCE_SHA256, filter_graph, process_audio, profile_for, split_script
import voxcpm_kaggle_worker as worker


def write_wave(path, values):
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        wav.writeframes(np.rint(np.asarray(values) * 32767).astype("<i2").tobytes())


def sound(seconds, ranges):
    values = np.zeros(round(seconds * 48000))
    for a, b, amplitude in ranges:
        x = np.arange(round((b-a) * 48000)) / 48000
        values[round(a*48000):round(a*48000)+len(x)] = amplitude * np.sin(2*np.pi*220*x)
    return values


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def job(self, **kwargs):
        return prepare_job(self.root / "jobs", "member", "owner/private-reference", "完整讲稿。", "日语", 16261109, self.root / "output", **kwargs)

    def source_clip(self):
        original, video = self.root/"source_voice.wav", self.root/"source_clip.mp4"
        write_wave(original,sound(4,[(0.4,0.9,0.1),(1.4,1.9,0.1),(2.4,2.9,0.1)]))
        command([tool("ffmpeg"),"-v","error","-y","-f","lavfi","-i","testsrc2=size=160x96:rate=25:duration=4","-i",str(original),"-c:v","libx264","-threads","1","-c:a","aac","-shortest",str(video)])
        return original, video

    def fake_cli(self, manifest_path, cleanup_fails=False, invalid_recipe=False):
        manifest = json.loads(manifest_path.read_text())
        self.calls = []
        def call(args, env, timeout=180):
            self.calls.append((list(args), dict(env)))
            if args[:2] == ["kernels", "status"]:
                return manifest["kernel"] + ' has status "KernelWorkerStatus.COMPLETE"'
            if args[:2] == ["kernels", "output"]:
                folder = Path(args[args.index("-p")+1])
                folder.mkdir(exist_ok=True)
                for name in ("yangning_raw.wav", "yangning_final.wav"):
                    write_wave(folder/name, sound(1, [(0.2, 0.8, 0.1)]))
                (folder/"script.txt").write_text("完整讲稿。")
                recipe = {"job_id": manifest["job_id"], "status": "generated_pending_review", "language": "日语",
                          "reference_sha256": "wrong" if invalid_recipe else REFERENCE_SHA256,
                          "template_audio_used": False, "silence_trimmed": False, "pitch_ratio": 1.0,
                          "profile": {"tempo": manifest["tempo"]}}
                (folder/"voice_recipe.json").write_text(json.dumps(recipe))
            if args[:2] == ["kernels", "delete"]:
                self.assertTrue(list((self.root/"output").glob("*.wav")))
                if cleanup_fails:
                    raise RuntimeError("temporary cleanup failure")
            return "ok"
        return call

    def test_notebook_code_is_valid_and_request_is_data(self):
        payload = '日本語。\n"\"\"); __import__("os").environ["UNWANTED"]="1" #'
        request = {"text": payload, "language": "日语", "seed": 1, "tempo": 0.95}
        notebook = build_notebook(request)
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code":
                compile("".join(cell["source"]), "generated_cell", "exec")
        namespace = {}
        exec("".join(notebook["cells"][2]["source"]), namespace)
        self.assertEqual(namespace["REQUEST"], request)
        self.assertNotIn("UNWANTED", os.environ)

    def test_subtitle_numbers_and_times_not_spoken(self):
        text = "1\n00:00:00,000 --> 00:00:01,000\n金剛経\n\n2\n00:00:01,000 --> 00:00:02,000\n32\n"
        self.assertEqual(script_from_text(text), "金剛経 32")

    def test_private_job_and_custom_speed(self):
        path = self.job(tempo=0.95)
        folder = path.parent
        meta = json.loads((folder/"kernel-metadata.json").read_text())
        self.assertTrue(meta["is_private"])
        self.assertTrue(meta["enable_gpu"])
        self.assertEqual(json.loads(path.read_text())["tempo"], 0.95)

    def test_language_default_and_tempo_validation(self):
        for lang in ("日语", "英语", "法语", "德语", "印尼语", "粤语"):
            self.assertEqual(profile_for(lang)["tempo"], 1.0)
        for value in (0, 3, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                profile_for("日语", value)
        self.assertIn("tempo=0.95:pitch=1:", filter_graph(0.95))
        self.assertNotIn("trim", filter_graph(0.95))

    def test_semantic_blocks_no_lost_text(self):
        text = "これは完整な文章です。" * 200
        blocks = split_script(text)
        self.assertGreater(len(blocks), 1)
        self.assertEqual("".join(blocks).replace(" ", ""), text)
        self.assertEqual(split_script("言葉、言葉、言葉。"), ["言葉、言葉、言葉。"])

    def test_auth_modern_and_legacy_no_stale_token(self):
        with patch.dict(os.environ, {"KAGGLE_API_TOKEN": "old", "KAGGLE_KEY": "oldkey"}):
            modern = auth_env("member", "KGAT_test-only", self.root)
            self.assertEqual(modern["KAGGLE_API_TOKEN"], "KGAT_test-only")
            self.assertNotIn("KAGGLE_KEY", modern)
            legacy = auth_env("member", "legacy-test-only", self.root)
            self.assertEqual(legacy["KAGGLE_KEY"], "legacy-test-only")
            self.assertNotIn("KAGGLE_API_TOKEN", legacy)

    def test_incomplete_is_not_complete(self):
        with self.assertRaises(RuntimeError):
            state_from_output('member/task has status "incomplete"')

    def test_results_saved_before_remote_cleanup(self):
        path = self.job()
        cli = self.fake_cli(path)
        artifacts = run_job(path, "KGAT_test-only", lambda event: None, cli=cli, sleep=lambda n: None)
        self.assertTrue(Path(artifacts["yangning_final.wav"]).exists())
        manifest = json.loads(path.read_text())
        self.assertEqual(manifest["cleanup_status"], "deleted")
        self.assertNotIn("KGAT_test-only", path.read_text())

    def test_submission_timeout_recovers_without_duplicate_push(self):
        path = self.job()
        def interrupted(args, env, timeout=180):
            raise TimeoutError("connection lost: KGAT_test-only")
        with self.assertRaises(RuntimeError):
            run_job(path, "KGAT_test-only", lambda e: None, cli=interrupted)
        self.assertEqual(json.loads(path.read_text())["status"], "submitting")
        self.assertNotIn("KGAT_test-only", path.read_text())
        cli = self.fake_cli(path)
        run_job(path, "KGAT_test-only", lambda e: None, cli=cli)
        self.assertFalse(any(args[:2] == ["kernels", "push"] for args, env in self.calls))

    def test_invalid_result_is_not_deleted(self):
        path = self.job()
        cli = self.fake_cli(path, invalid_recipe=True)
        with self.assertRaises(RuntimeError):
            run_job(path, "KGAT_test-only", lambda e: None, cli=cli)
        self.assertFalse(any(args[:2] == ["kernels", "delete"] for args, env in self.calls))

    def test_cleanup_failure_keeps_success_and_retry_does_not_regenerate(self):
        path = self.job()
        run_job(path, "legacy", lambda e: None, cli=self.fake_cli(path, cleanup_fails=True))
        self.assertEqual(json.loads(path.read_text())["status"], "completed")
        cli = self.fake_cli(path)
        run_job(path, "legacy", lambda e: None, cli=cli)
        self.assertEqual([args[1] for args, env in self.calls], ["delete"])

    def test_local_export_failure_resumes_from_saved_audio(self):
        path = self.job(edit={"mode":"partial","video":"fixture","start":1,"end":2})
        with patch("voice_clip_edit.preflight_edit"), patch("voice_clip_edit.export_edited_clip", side_effect=ValueError("接点需扩大")):
            with self.assertRaises(RuntimeError):
                run_job(path,"legacy",lambda e:None,cli=self.fake_cli(path))
        self.assertEqual(json.loads(path.read_text())["status"],"audio_ready")
        cli=self.fake_cli(path)
        with patch("voice_clip_edit.export_edited_clip", return_value={"edited_video":"fixture-complete.mp4"}):
            result=run_job(path,"legacy",lambda e:None,cli=cli)
        self.assertEqual(result["edited_video"],"fixture-complete.mp4")
        self.assertEqual([args[1] for args, env in self.calls],["delete"])

    def test_worker_with_model_stub_applies_recipe_and_gpu_dtype_fallback(self):
        reference=self.root/"1626_reference.wav"
        write_wave(reference,sound(1,[(0.2,0.8,0.1)]))
        snapshot=self.root/"snapshot-revision"
        snapshot.mkdir()
        (snapshot/"config.json").write_text(json.dumps({"dtype":"bfloat16"}))
        calls=[]
        def load(path, **kwargs):
            self.assertEqual(json.loads((Path(path)/"config.json").read_text())["dtype"],"float32")
            self.assertFalse(kwargs["load_denoiser"])
            def generate(**parameters):
                calls.append(parameters)
                return sound(1,[(0.2,0.8,0.1)])
            return SimpleNamespace(tts_model=SimpleNamespace(sample_rate=48000),generate=generate)
        modules={
            "torch":SimpleNamespace(manual_seed=lambda n:None,cuda=SimpleNamespace(manual_seed_all=lambda n:None,is_available=lambda:True,is_bf16_supported=lambda:False,get_device_name=lambda n:"TEST GPU")),
            "huggingface_hub":SimpleNamespace(snapshot_download=lambda *a,**k:str(snapshot)),
            "voxcpm":SimpleNamespace(VoxCPM=SimpleNamespace(from_pretrained=load)),
            "soundfile":SimpleNamespace(write=lambda path,values,rate,subtype:write_wave(path,values)),
        }
        output=self.root/"worker-output"
        from voice_prosody import analyze_template
        template_profile = analyze_template(reference)
        with patch.dict("sys.modules",modules), patch.object(worker,"REFERENCE_SHA256",hashlib.sha256(reference.read_bytes()).hexdigest()):
            worker.run({"job_id":"test","reference_path":str(reference),"text":"正しい日本語。","language":"日语","seed":16261109,"tempo":0.95,"output_dir":str(output),"prosody_reference":template_profile})
        self.assertIsNone(calls[0]["prompt_wav_path"])
        self.assertIsNone(calls[0]["prompt_text"])
        self.assertIn("Warm, gentle Japanese narration",calls[0]["text"])
        self.assertIn(template_profile["instruction"], calls[0]["text"])
        self.assertEqual(calls[0]["reference_wav_path"], str(reference))
        self.assertNotIn("seed", calls[0])
        recipe=json.loads((output/"voice_recipe.json").read_text())
        self.assertEqual(recipe["profile"]["tempo"],0.95)
        self.assertFalse(recipe["silence_trimmed"])
        self.assertEqual(recipe["model_dtype"],"float32")
        self.assertEqual(recipe["review"]["音色"],"待听检")

    def test_template_summary_is_data_only_and_never_changes_tempo(self):
        from voice_prosody import analyze_template
        template = self.root / "template.wav"
        write_wave(template, sound(2, [(0.1,0.7,0.1),(1.0,1.8,0.1)]))
        summary = analyze_template(template)
        self.assertFalse(summary["template_waveform_sent_to_model"])
        self.assertFalse(summary["absolute_pitch_transferred"])
        self.assertFalse(summary["tempo_changed_by_template"])
        path = self.job(prosody_template=str(template))
        notebook = json.loads((path.parent/"voxcpm2.ipynb").read_text())
        setup = "".join(notebook["cells"][2]["source"])
        self.assertIn(summary["source_sha256"], setup)
        self.assertNotIn(str(template), setup)
        self.assertNotIn("base64", setup)
        self.assertEqual(json.loads(path.read_text())["tempo"], 1.0)

    def test_worker_rejects_unapproved_reference_before_model_loading(self):
        reference=self.root/"wrong.wav"
        reference.write_bytes(b"wrong-reference")
        modules={"torch":SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True)),
                 "soundfile":SimpleNamespace(),"voxcpm":SimpleNamespace(VoxCPM=SimpleNamespace()),
                 "huggingface_hub":SimpleNamespace(snapshot_download=lambda *a,**k:None)}
        with patch.dict("sys.modules",modules),self.assertRaises(ValueError):
            worker.run({"reference_path":str(reference),"language":"日语","text":"test"})

    def test_invalid_subtitle_selection_is_rejected_before_gpu_submission(self):
        audio,video=self.source_clip()
        srt=self.root/"crossing.srt"
        write_srt([{"start":1.0,"end":2.5,"text":"complete sentence"}],srt)
        path=self.job(edit={"mode":"partial","video":str(video),"audio":str(audio),"srt":str(srt),"start":1.2,"end":2.2})
        cli=self.fake_cli(path)
        with self.assertRaises(RuntimeError):
            run_job(path,"legacy",lambda e:None,cli=cli)
        self.assertEqual(self.calls,[])
        self.assertEqual(json.loads(path.read_text())["status"],"prepared")

    def test_changed_source_is_detected_before_local_render(self):
        audio,video=self.source_clip()
        replacement=self.root/"replace.wav"
        write_wave(replacement,sound(1,[(0.2,0.8,0.1)]))
        edit={"mode":"partial","video":str(video),"audio":str(audio),"srt":"","start":1.2,"end":2.2,"text":"corrected"}
        preflight_edit(edit,self.root/"snapshot")
        self.assertTrue(Path(edit["_prepared_audio"]).exists())
        with video.open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError,"原视频文件已变化"):
            export_edited_clip(edit,replacement,self.root,"changed")
        self.assertFalse((self.root/"VoiceEdit_changed"/"complete_video.mp4").exists())

    def test_preview_media_check_requires_both_real_tools(self):
        import cloud_voice_preview as preview
        media=self.root/"tools"
        media.mkdir()
        suffix=".exe" if os.name=="nt" else ""
        (media/("ffmpeg"+suffix)).touch()
        with patch.object(preview.subprocess,"run") as run:
            self.assertFalse(preview.usable_tools(media))
            (media/("ffprobe"+suffix)).touch()
            run.side_effect=lambda args,**kw:SimpleNamespace(returncode=0,stdout=(Path(args[0]).stem+" version test").encode())
            self.assertTrue(preview.usable_tools(media))

    def test_file_based_python_probe_handles_spaced_directory(self):
        folder=self.root/"preview probe with spaces 日本語"
        folder.mkdir()
        target=folder/"preview_python_check.py"
        target.write_text(Path(__file__).with_name("preview_python_check.py").read_text(),encoding="utf-8")
        result=subprocess.run([sys.executable,"-I",str(target)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(Path(json.loads(result.stdout)).resolve(),Path(sys.executable).resolve())

    def test_partial_preserves_unmodified_samples_and_retimes_subtitles(self):
        original, clip, output = [self.root/name for name in ("original.wav", "clip.wav", "edited.wav")]
        source = sound(4, [(0.4,0.9,0.1), (1.4,1.9,0.1), (2.4,2.9,0.1), (3.4,3.8,0.1)])
        write_wave(original, source)
        write_wave(clip, sound(1.5, [(0.2,1.0,0.08)]))
        timing = patch_audio(original, clip, output, 1.2, 2.2)
        self.assertAlmostEqual(timing["new_seconds"], 4.5)
        np.testing.assert_array_equal(read_frames(original,0,48000), read_frames(output,0,48000))
        np.testing.assert_array_equal(read_frames(original,3*48000,4*48000), read_frames(output,round(3.5*48000),round(4.5*48000)))
        cues = [{"start":0.4,"end":0.9,"text":"first"}, {"start":1.4,"end":1.9,"text":"wrong"}, {"start":2.4,"end":2.9,"text":"last"}]
        updated = remap_subtitles(cues, timing, "corrected")
        self.assertAlmostEqual(updated[-1]["start"],2.9)
        self.assertEqual(updated[1]["text"], "corrected")
        self.assertEqual(timing["replacement_samples_removed"],0)

    def test_partial_rejects_cuts_inside_speech(self):
        original, clip, output = [self.root/name for name in ("original.wav", "clip.wav", "edited.wav")]
        write_wave(original,sound(4,[(0,4,0.1)]))
        write_wave(clip,sound(1,[(0.2,0.8,0.1)]))
        with self.assertRaises(ValueError):
            patch_audio(original,clip,output,1,2)

    def test_audio_only_patch_exports_complete_wav_and_preserves_original(self):
        from voice_clip_edit import preflight_audio_edit, export_edited_audio
        original, replacement = self.root/"original.wav", self.root/"new_sentence.wav"
        write_wave(original,sound(4,[(0.4,0.9,0.1),(1.4,1.9,0.1),(2.4,2.9,0.1)]))
        write_wave(replacement,sound(1.5,[(0.2,1.0,0.08)]))
        checksum = hashlib.sha256(original.read_bytes()).hexdigest()
        subtitles = self.root/"current.srt"
        write_srt([{"start":0.4,"end":0.9,"text":"first"},{"start":1.4,"end":1.9,"text":"wrong"},{"start":2.4,"end":2.9,"text":"last"}],subtitles)
        edit={"kind":"audio","mode":"partial","audio":str(original),"srt":str(subtitles),"start":1.2,"end":2.2,"text":"Corrected."}
        preflight_audio_edit(edit,self.root/"cache")
        result = export_edited_audio(edit,replacement,self.root/"output","test")
        self.assertAlmostEqual(wav_info(result["edited_audio"])[1],4.5)
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),checksum)
        self.assertFalse(list((self.root/"output").rglob("*.mp4")))
        np.testing.assert_array_equal(read_frames(original,0,48000),read_frames(result["edited_audio"],0,48000))
        np.testing.assert_array_equal(read_frames(original,3*48000,4*48000),read_frames(result["edited_audio"],int(3.5*48000),int(4.5*48000)))
        self.assertAlmostEqual(read_srt(result["edited_srt"])[-1]["start"],2.9)
        self.assertTrue(Path(result["join_left"]).is_file())
        self.assertTrue(Path(result["join_right"]).is_file())

    def test_audio_correction_preflight_rejects_speech_cut_before_gpu(self):
        original = self.root/"speech.wav"
        write_wave(original,sound(4,[(0,4,0.1)]))
        manifest = self.job(edit={"kind":"audio","mode":"partial","audio":str(original),"srt":"","start":1,"end":2})
        cli = self.fake_cli(manifest)
        with self.assertRaisesRegex(RuntimeError,"安静的接点"):
            run_job(manifest,"legacy",lambda e:None,cli=cli,sleep=lambda _:None,audio_only=True)
        self.assertEqual(self.calls,[])

    def test_audio_correction_local_failure_recovers_without_generating_again(self):
        from voice_clip_edit import export_edited_audio
        original = self.root/"original.wav"
        write_wave(original,sound(4,[(0.4,0.9,0.1),(1.4,1.9,0.1),(2.4,2.9,0.1)]))
        manifest = self.job(edit={"kind":"audio","mode":"partial","audio":str(original),"srt":"","start":1.2,"end":2.2})
        cli = self.fake_cli(manifest)
        with patch("voice_clip_edit.export_edited_audio",side_effect=RuntimeError("temporary local export failure")),self.assertRaises(RuntimeError):
            run_job(manifest,"legacy",lambda e:None,cli=cli,sleep=lambda _:None,audio_only=True)
        self.assertEqual(json.loads(manifest.read_text())["status"],"audio_ready")
        self.calls.clear()
        result=run_job(manifest,"legacy",lambda e:None,cli=cli,sleep=lambda _:None,audio_only=True)
        self.assertTrue(Path(result["edited_audio"]).is_file())
        self.assertEqual([args[1] for args,env in self.calls],["delete"])

    def test_real_ffmpeg_pitch_duration_and_pause_preservation(self):
        original = self.root/"raw.wav"
        write_wave(original,sound(2.9,[(0.2,1.05,0.2),(1.85,2.7,0.2)]))
        for tempo in (0.84,0.9,0.95,1.1):
            final = self.root/f"tempo{tempo}.wav"
            result = process_audio(original,final,tempo)
            self.assertAlmostEqual(result["final_seconds"],2.9/tempo,delta=0.08)
            silence = read_frames(final,round(1.25/tempo*48000),round(1.65/tempo*48000))
            self.assertLess(float(np.sqrt(np.mean(silence**2))),0.002)
            tone = read_frames(final,round(0.4/tempo*48000),round(0.8/tempo*48000))
            spectrum = np.abs(np.fft.rfft(tone*np.hanning(len(tone))))
            frequency = np.fft.rfftfreq(len(tone),1/48000)[np.argmax(spectrum)]
            self.assertAlmostEqual(frequency,220,delta=4)

    def test_real_partial_and_full_video_export(self):
        original = self.root/"voice.wav"
        clip = self.root/"replacement.wav"
        video = self.root/"source.mp4"
        write_wave(original,sound(4,[(0.4,0.9,0.1),(1.4,1.9,0.1),(2.4,2.9,0.1),(3.4,3.8,0.1)]))
        write_wave(clip,sound(1.5,[(0.2,1.0,0.1)]))
        command([tool("ffmpeg"),"-v","error","-y","-f","lavfi","-i","testsrc2=size=160x96:rate=25:duration=4","-i",str(original),"-c:v","libx264","-threads","1","-c:a","aac","-shortest",str(video)])
        srt = self.root/"source.srt"
        write_srt([{"start":0.4,"end":0.9,"text":"first"},{"start":1.4,"end":1.9,"text":"wrong"},{"start":2.4,"end":2.9,"text":"last"}],srt)
        edit={"mode":"partial","video":str(video),"audio":str(original),"srt":str(srt),"start":1.2,"end":2.2,"text":"Corrected sentence."}
        result=export_edited_clip(edit,clip,self.root,"partial")
        self.assertTrue(Path(result["edited_video"]).is_file())
        self.assertAlmostEqual(float(probe(result["edited_video"])["format"]["duration"]),4.5,delta=0.12)
        self.assertAlmostEqual(read_srt(result["edited_srt"])[-1]["start"],2.9,delta=0.002)
        self.assertTrue((self.root/"VoiceEdit_partial"/"join_left.wav").exists())
        full=export_edited_clip({**edit,"mode":"full"},clip,self.root,"full")
        self.assertAlmostEqual(float(probe(full["edited_video"])["format"]["duration"]),1.5,delta=0.12)
        self.assertTrue(video.exists())


if __name__ == "__main__":
    unittest.main()
