import json
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from cloud_voice_test import write_wave,sound
import cloud_voice_core as core
import voxcpm_kaggle_worker as worker
from voice_workflows import audition_text,terminology_text,load_segments
from voice_clip_edit import preflight_audio_edit,export_edited_audio

class NewWorkflowTests(unittest.TestCase):
    def test_audition_keeps_complete_sentences_and_terms(self):
        text='First complete sentence. Second complete sentence. '+('Third complete sentence. '*20)
        preview=audition_text(text,'英语')
        self.assertTrue(text.startswith(preview))
        self.assertTrue(preview.endswith('.'))
        self.assertLess(len(preview),len(text))
        self.assertIn('金剛経',terminology_text('金剛経と涅槃。','日语'))
        self.assertEqual(terminology_text('Dharma\nKarma\nDharma','英语'),'Dharma. Karma.')

    def test_failed_worker_resumes_only_missing_unit_and_cleans_chain_after_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);reference=root/'ref.wav';write_wave(reference,sound(1,[(.2,.8,.1)]))
            refhash=hashlib.sha256(reference.read_bytes()).hexdigest()
            snapshot=root/'snapshot-revision';snapshot.mkdir();(snapshot/'config.json').write_text('{"dtype":"float32"}')
            folder=root/'jobs'/'first';folder.mkdir(parents=True)
            download=folder/'download';calls=[];fail=[True]
            def load(*args,**kwargs):
                def generate(**params):
                    calls.append(params['text'])
                    if fail[0] and params['text'].endswith('Two.'): raise RuntimeError('simulated worker interruption')
                    return sound(1,[(.2,.8,.1)])
                return SimpleNamespace(tts_model=SimpleNamespace(sample_rate=48000),generate=generate)
            modules={
                'torch':SimpleNamespace(manual_seed=lambda n:None,cuda=SimpleNamespace(manual_seed_all=lambda n:None,is_available=lambda:True,is_bf16_supported=lambda:True,get_device_name=lambda n:'TEST GPU')),
                'huggingface_hub':SimpleNamespace(snapshot_download=lambda *a,**k:str(snapshot)),
                'voxcpm':SimpleNamespace(VoxCPM=SimpleNamespace(from_pretrained=load)),
                'soundfile':SimpleNamespace(),
            }
            request={'job_id':'first','text':'One. Two.','language':'英语','seed':10,'tempo':1.,'reference_path':str(reference),
                     'postprocess':{'gain_db':0.,'light_denoise':False},'units':[{'text':'One.','reading_text':'One.'},{'text':'Two.','reading_text':'Two.'}], 'output_dir':str(download)}
            core.save_json(folder/'request.json',request)
            core.save_json(folder/'manifest.json',{'job_id':'first','username':'member','dataset':'owner/reference','kernel':'member/old',
                 'language':'英语','tempo':1.,'output_dir':str(root/'delivered'),'status':'remote_failed','postprocess':request['postprocess'],'purpose':'full'})
            original_rglob=Path.rglob
            def listing(path,pattern):
                if str(path)=='/kaggle/input': return iter([reference] if pattern=='*' else [download/'checkpoint_manifest.json'])
                return original_rglob(path,pattern)
            with patch.dict('sys.modules',modules),patch.object(worker,'REFERENCE_SHA256',refhash),patch.object(core,'REFERENCE_SHA256',refhash),patch.object(Path,'rglob',listing):
                with self.assertRaisesRegex(RuntimeError,'interruption'): worker.run(request)
                record,parts=worker.checkpoint_parts(download/'checkpoint_manifest.json',request)
                self.assertEqual(list(parts),[0])
                manifest=core.prepare_resume_job(folder/'manifest.json')
                metadata=json.loads((manifest.parent/'kernel-metadata.json').read_text())
                self.assertEqual(metadata['kernel_sources'],['member/old'])
                retry=json.loads((manifest.parent/'request.json').read_text());retry['output_dir']=str(root/'complete')
                fail[0]=False;worker.run(retry)
                self.assertEqual(len(calls),3)
                self.assertEqual(sum(text.endswith('One.') for text in calls),1)
                recipe=json.loads((root/'complete'/'voice_recipe.json').read_text())
                self.assertEqual(recipe['resumed_segments'],1)
                deleted=[]
                def cli(args,env,timeout=180):
                    if args[:2]==['kernels','status']: return 'has status "COMPLETE"'
                    if args[:2]==['kernels','output']:
                        dest=Path(args[args.index('-p')+1]);shutil.copytree(root/'complete',dest,dirs_exist_ok=True)
                    if args[:2]==['kernels','delete']:
                        self.assertTrue(list((root/'delivered').glob('*.wav')));deleted.append(args[2])
                    return 'ok'
                artifacts=core.run_job(manifest,'legacy',lambda event:None,cli=cli,sleep=lambda n:None,audio_only=True)
                self.assertEqual(len(deleted),2)
                segments=load_segments(artifacts['yangning_final.wav'])
                self.assertEqual([item['text'] for item in segments['segments']],['One.','Two.'])
                # Corrupted checkpoints must not be accepted or silently regenerated.
                cp=download/'checkpoints'/'part_00000.npz';cp.write_bytes(b'corrupt')
                with self.assertRaises(ValueError): worker.checkpoint_parts(download/'checkpoint_manifest.json',request)

    def test_notebook_preserves_handled_errors_and_client_never_reports_them_as_audio(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            notebook=core.build_notebook({"job_id":"guard","text":"One","language":"英语"})
            source="".join(notebook["cells"][-1]["source"])
            guard=source[source.rindex("\ntry:\n    run(REQUEST)"):]
            def fail(request): raise RuntimeError("controlled generation error")
            exec(guard,{"REQUEST":{"job_id":"guard","output_dir":str(root/"handled")},"run":fail,"Path":Path,"atomic_json":core.save_json})
            self.assertEqual(json.loads((root/"handled"/"job_failure.json").read_text())["status"],"failed_with_saved_outputs")
            manifest=core.prepare_job(root/"jobs","member","owner/reference","One.","英语",1,root/"out")
            job=json.loads(manifest.read_text())
            def cli(args,env,timeout=180):
                if args[:2]==['kernels','status']: return 'has status "COMPLETE"'
                if args[:2]==['kernels','output']:
                    folder=Path(args[args.index('-p')+1]);folder.mkdir(exist_ok=True)
                    core.save_json(folder/'job_failure.json',{'job_id':job['job_id'],'error':'controlled interruption'})
                if args[:2]==['kernels','delete']: raise AssertionError('Do not delete retained failed outputs')
                return 'ok'
            with self.assertRaisesRegex(RuntimeError,'已保存0段'):
                core.run_job(manifest,'legacy',lambda event:None,cli=cli)
            self.assertEqual(json.loads(manifest.read_text())["status"],"remote_failed")

    def test_edited_audio_retains_usable_sentence_table(self):
        from voice_review import file_sha256
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'original.wav';replacement=root/'new.wav'
            write_wave(source,sound(4,[(.3,.7,.1),(1.3,1.7,.1),(2.3,2.7,.1)]))
            write_wave(replacement,sound(1,[(.2,.8,.1)]))
            Path(str(source)+'.segments.json').write_text(json.dumps({'audio_sha256':file_sha256(source),'timing':'generated_units','segments':[
                {'start':0,'end':1,'text':'A'},{'start':1,'end':2,'text':'B'},{'start':2,'end':4,'text':'C'}]}))
            edit={'audio':str(source),'start':1,'end':2,'text':'New B','srt':''}
            preflight_audio_edit(edit,root/'snapshot')
            result=export_edited_audio(edit,replacement,root,'edit')
            mapped=load_segments(result['edited_audio'])
            self.assertEqual([item['text'] for item in mapped['segments']],['A','New B','C'])
            self.assertTrue(source.is_file())
            # A retry must not silently snapshot a changed source after interruption.
            source.write_bytes(source.read_bytes()+b"changed")
            with self.assertRaisesRegex(ValueError,"原音频在断点任务后已变化"):
                preflight_audio_edit(edit,root/'retry_snapshot')

if __name__=='__main__': unittest.main()
