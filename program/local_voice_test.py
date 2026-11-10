"""Local backend routing, persistent model lifetime and isolated process tests."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cloud_voice_core as core
import local_voice as local
import voxcpm_kaggle_worker as worker
from cloud_voice_test import sound,write_wave


class LocalTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.ref=self.root/"teacher.wav";write_wave(self.ref,sound(1,[(.1,.8,.1)]))
        sha=hashlib.sha256(self.ref.read_bytes()).hexdigest()
        for module in (local,core,worker):
            guard=patch.object(module,"REFERENCE_SHA256",sha);guard.start();self.addCleanup(guard.stop)
        guard=patch.dict(os.environ,{"YANGNING_CLOUD_DATA_DIR":str(self.root/"data")});guard.start();self.addCleanup(guard.stop)

    def job(self,text="金剛経。"):
        return core.prepare_job(self.root/"jobs","","",text,"日语",42,self.root/"output",execution="local",local_reference=str(self.ref),local_device="cpu",include_preview=True)

    def test_two_local_requests_load_model_once_and_need_no_kaggle(self):
        snapshot=self.root/"snapshot";snapshot.mkdir();(snapshot/"config.json").write_text('{"dtype":"bfloat16"}')
        calls=[];loads=[]
        def load(path,**kwargs):
            loads.append(kwargs);self.assertEqual(kwargs["device"],"cpu")
            self.assertFalse(kwargs["optimize"])
            self.assertEqual(json.loads((Path(path)/"config.json").read_text())["dtype"],"float32")
            def generate(**parameters):
                calls.append(parameters);return sound(1,[(.1,.8,.1)])
            return SimpleNamespace(tts_model=SimpleNamespace(sample_rate=48000),generate=generate)
        modules={"torch":SimpleNamespace(manual_seed=lambda n:None,cuda=SimpleNamespace(is_available=lambda:False)),
                 "huggingface_hub":SimpleNamespace(snapshot_download=lambda *a,**k:str(snapshot)),
                 "voxcpm":SimpleNamespace(VoxCPM=SimpleNamespace(from_pretrained=load)),"soundfile":SimpleNamespace()}
        context={"cache_dir":str(self.root/"models"),"device":"cpu"}
        class Engine:
            def execute(engine,path,emit): worker.run(json.loads(Path(path).read_text()),local_context=context)
        report={"available_gb":32,"gpus":[]}
        try:
            with patch.dict("sys.modules",modules),patch.object(local,"hardware_report",return_value=report),patch.object(core,"kaggle_cli",side_effect=AssertionError("cloud must not be called")):
                first=self.job("1\n00:00:00,000 --> 00:00:00,500\n金剛経。\n\n2\n00:00:02,000 --> 00:00:03,000\n涅槃。");result=local.run_local_job(first,lambda e:None,engine=Engine())
                local.run_local_job(self.job("涅槃。"),lambda e:None,engine=Engine())
                local.run_local_job(first,lambda e:None,engine=Engine())
            self.assertEqual(len(loads),1)
            self.assertEqual(len(calls),3)
            report=json.loads(Path(result["timing_report.json"]).read_text())
            self.assertEqual(report["overrun_count"],1)
            self.assertEqual(report["shifted_count"],1)
            self.assertTrue(Path(result["preview_audio"]).is_file())
            for call in calls:
                self.assertEqual(call["reference_wav_path"],str(self.ref))
                self.assertIsNone(call["prompt_wav_path"])
            self.assertFalse(json.loads(first.read_text())["cloud_submitted"])
        finally:
            if context.get("runtime"): shutil.rmtree(context["runtime"],ignore_errors=True)

    def test_wrong_reference_is_rejected_before_local_setup_or_cloud(self):
        self.ref.write_bytes(b"wrong voice")
        with self.assertRaisesRegex(ValueError,"老师原声"): self.job()

    def test_environment_commands_are_isolated_and_use_matching_torch_pair(self):
        calls=[]
        with patch.object(local,"hardware_report",return_value={"gpus":[]}),patch.object(local.shutil,"disk_usage",return_value=SimpleNamespace(free=100*1024**3)):
            local.prepare_environment(lambda e:None,runner=lambda args,**kwargs:calls.append(args))
        self.assertIn("venv",calls[0])
        self.assertIn("torch==2.6.0",calls[1]);self.assertIn("torchaudio==2.6.0",calls[1])
        self.assertIn("https://download.pytorch.org/whl/cpu",calls[1])
        self.assertNotEqual(str(local.python_path()),sys.executable)
        self.assertTrue((local.local_root()/"ready.json").is_file())

    def test_real_private_pipe_reuses_one_process_and_releases_it(self):
        service=self.root/"pipe_fixture.py"
        service.write_text('import sys,json\nfor line in sys.stdin:\n value=json.loads(line)\n if value.get("shutdown"): break\n print("YANGNING_LOCAL="+json.dumps({"status":"done"}),flush=True)\n')
        local.local_root().mkdir(parents=True);(local.local_root()/"ready.json").write_text('{}')
        engine=local.LocalEngine(service);self.addCleanup(engine.stop)
        request=self.root/"request.json";request.write_text('{}')
        with patch.object(local,"python_path",return_value=Path(sys.executable)):
            engine.execute(request,lambda e:None);first=engine.process
            engine.execute(request,lambda e:None)
            self.assertIs(engine.process,first)
            engine.stop();self.assertIsNotNone(first.poll())

    def test_low_memory_stops_before_loading(self):
        path=self.job()
        with patch.object(local,"hardware_report",return_value={"available_gb":2,"gpus":[]}):
            with self.assertRaisesRegex(ValueError,"可用内存不足"):
                local.run_local_job(path,lambda e:None,engine=SimpleNamespace(execute=lambda *a:self.fail("must not load")))
