import hashlib
import json
from pathlib import Path
import tempfile
import threading
from datetime import datetime,timezone
import unittest
from unittest.mock import patch
import wave
import numpy as np
import cloud_voice_core as core
import voxcpm_kaggle_worker as worker
from voice_workflows import audition_text


SRT="7\n00:00:01,000 --> 00:00:02,000\n第一句。\n\n12\n00:00:04,000 --> 00:00:05,000\n第二句。"


class TimingTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)

    def pieces(self,lengths):
        parts=[]
        for i,length in enumerate(lengths):
            path=self.root/f"{i}.npz"
            values=np.full(round(length*48000),.125,dtype=np.float32)
            with path.open("wb") as stream:np.savez(stream,audio=values)
            parts.append({"file":path.name})
        return parts

    def assemble(self,lengths,tempo=1):
        cues=worker.parse_srt_cues(SRT)
        request={"srt_cues":cues,"tempo":tempo,"units":[{"text":c["text"]} for c in cues]}
        target=self.root/"raw.wav"
        segments,report=worker.compose_timed_wav(request,self.pieces(lengths),self.root,target,48000,1)
        with wave.open(str(target),"rb") as audio:values=np.frombuffer(audio.readframes(audio.getnframes()),dtype="<i2")
        return values,segments,report

    def test_complete_ids_multiline_bom_and_overlap_rejected(self):
        cues=worker.parse_srt_cues("\ufeff"+SRT.replace("第一句。","<b>第一句。</b>\n追加行。").replace("\n","\r\n"))
        self.assertEqual([c["index"] for c in cues],[7,12]);self.assertEqual(cues[0]["start_ms"],1000)
        self.assertEqual(cues[0]["text"],"第一句。 追加行。")
        for invalid in (SRT.replace("00:00:04,000","00:00:01,500"),SRT.replace("12\n","7\n"),SRT.replace("00:00:01,000","00:61:01,000"),"第一句。\n00:00:01,000 --> 00:00:02,000\n正文"):
            with self.assertRaises(ValueError):worker.parse_srt_cues(invalid)

    def test_short_cues_start_exactly_on_timeline_and_keep_all_padding(self):
        values,segments,report=self.assemble([.5,.5])
        self.assertEqual(len(values),5*48000)
        self.assertEqual([s["start"] for s in segments],[1,4]);self.assertEqual(report["overrun_count"],0)
        self.assertFalse(values[:48000].any());self.assertFalse(values[72000:192000].any())
        self.assertEqual(np.count_nonzero(values),48000)

    def test_overlong_cue_is_not_cut_and_shifts_next_with_original_gap(self):
        values,segments,report=self.assemble([2,.5])
        self.assertEqual(segments[0]["end"],3);self.assertEqual(segments[1]["start"],5)
        self.assertEqual(report["overrun_count"],1);self.assertEqual(report["shifted_count"],1)
        self.assertEqual(np.count_nonzero(values),int(2.5*48000))
        self.assertEqual(len(values),int(5.5*48000))

    def test_speed_changes_speech_but_not_srt_silence_times(self):
        values,segments,report=self.assemble([1,1],tempo=2)
        self.assertEqual([s["start"] for s in segments],[1,4]);self.assertEqual(len(values),5*48000)
        self.assertLess(segments[0]["end"],1.6)

    def test_long_srt_pause_is_not_capped_to_thirty_seconds(self):
        cues=worker.parse_srt_cues(SRT.replace("00:00:01,000","00:01:01,000").replace("00:00:02,000","00:01:02,000").replace("00:00:04,000","00:01:04,000").replace("00:00:05,000","00:01:05,000"))
        target=self.root/"long.wav"
        segments,_=worker.compose_timed_wav({"srt_cues":cues,"units":[{"text":c["text"]} for c in cues]},self.pieces([.1,.1]),self.root,target,48000,1)
        self.assertEqual(segments[0]["start"],61)

    def test_txt_commas_periods_questions_newlines_without_number_damage(self):
        text="Dr. Smith has 1,000 items, and 3.14 examples.\n这是一个较长的中文分句，接着说下一句。还有问题吗？"
        units=worker.text_pause_units(text)
        self.assertEqual("".join(text.split()),"".join("".join(u["text"] for u in units).split()))
        self.assertTrue(any("1,000" in u["text"] for u in units));self.assertTrue(any("3.14" in u["text"] for u in units))
        self.assertTrue(any(u["pause_after"]==.18 for u in units));self.assertTrue(any(u["pause_after"]==.65 for u in units))
        req={"units":[{"text":"一句，","pause_after":.18},{"text":"第二句。","pause_after":0}]}
        target=self.root/"txt.wav"
        segments,_=worker.compose_timed_wav(req,self.pieces([.5,.5]),self.root,target,48000,1)
        self.assertAlmostEqual(segments[1]["start"],.68)

    def test_srt_survives_preparation_notebook_and_hash_changes_with_timing(self):
        job=core.prepare_job(self.root/"jobs","member","owner/private",SRT,"日语",1,self.root/"out")
        request=json.loads((job.parent/"request.json").read_text())
        self.assertEqual(request["srt_cues"][1]["index"],12)
        self.assertEqual(request["units"][0]["reading_text"],"第一句。")
        changed=json.loads(json.dumps(request));changed["srt_cues"][0]["start_ms"]+=100
        self.assertNotEqual(worker.request_fingerprint(changed),worker.request_fingerprint(request))
        for cell in core.build_notebook(request)["cells"]:
            if cell["cell_type"]=="code":compile("".join(cell["source"]),"notebook","exec")
        self.assertIn("-->",audition_text(SRT,"日语"))

    def test_cancel_before_submission_never_calls_cloud(self):
        job=core.prepare_job(self.root/"jobs","member","owner/private","正文。","日语",1,self.root/"out")
        event=threading.Event();event.set()
        with self.assertRaises(core.JobCancelled):
            core.run_job(job,"",lambda e:None,cli=lambda *a,**k:self.fail("cloud call"),cancel_event=event)
        self.assertEqual(json.loads(job.read_text())["status"],"cancelled")

    def test_cloud_cancel_targets_only_current_job_and_does_not_claim_failure_as_success(self):
        for fail in (False,True):
            job=core.prepare_job(self.root/"jobs","member","owner/private","正文。","日语",1,self.root/"out")
            record=json.loads(job.read_text());record["status"]="submitted";core.save_json(job,record)
            event=threading.Event();event.set();calls=[]
            def cli(args,*a,**k):
                calls.append(args)
                if fail:raise RuntimeError("permission denied")
                return "deleted"
            with self.assertRaises(RuntimeError):core.run_job(job,"test-secret",lambda e:None,cli=cli,cancel_event=event)
            self.assertEqual(calls,[["kernels","delete",record["kernel"],"--yes"]])
            self.assertEqual(json.loads(job.read_text())["status"],"cancel_pending" if fail else "cancelled")

    def test_japan_stamp_rolls_date_at_utc_midnight_offset(self):
        frozen=datetime(2026,11,10,23,58,tzinfo=timezone.utc)
        class Clock:
            @staticmethod
            def now(tz):return frozen.astimezone(tz)
        with patch.object(core,"datetime",Clock):self.assertEqual(core.japan_stamp(),"20261111_085800_JST")
