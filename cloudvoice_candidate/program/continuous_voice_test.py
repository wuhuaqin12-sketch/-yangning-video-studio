import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from cloud_voice_core import prepare_job
from voxcpm_kaggle_worker import generation_blocks,continuous_generate,request_fingerprint

class ContinuousVoiceTests(unittest.TestCase):
 def test_txt_and_srt_are_one_request(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   scripts=['第一句，第二句。\n第三句？','8\n00:00:01,000 --> 00:00:03,000\n第一句。\n\n9\n00:00:05,000 --> 00:00:08,000\n第二句？']
   for i,text in enumerate(scripts):
    p=prepare_job(root/'jobs','member','owner/reference',text,'日语',1,root/'out',include_preview=True)
    r=json.loads((p.parent/'request.json').read_text())
    self.assertEqual(r['generation_mode'],'continuous_full_text')
    self.assertEqual(len(r['units']),1);self.assertEqual(len(generation_blocks(r)),1)
    self.assertNotIn('unit_pauses',r)
    if i:
     self.assertEqual(r['srt_cues'][0]['index'],8)
     self.assertEqual(r['srt_timing_policy'],'source_reference_only')
    self.assertTrue(r['include_preview'])
 def fake_model(self,stop=1,tokens=100):
  calls=[]
  class Head:
   removed=False
   def register_forward_hook(self,callback):self.callback=callback;return SimpleNamespace(remove=lambda:setattr(self,'removed',True))
  head=Head()
  def generate(text,seed=None,**kwargs):
   calls.append(dict(text=text,seed=seed,**kwargs))
   output=SimpleNamespace(argmax=lambda **k:[SimpleNamespace(cpu=lambda:SimpleNamespace(item=lambda:stop))])
   head.callback(head,(),output)
   return [0.0,0.2,0.0]
  model=SimpleNamespace(tts_model=SimpleNamespace(stop_head=head,text_tokenizer=lambda t:[0]*tokens,config=SimpleNamespace(max_length=8192)),generate=generate)
  return model,calls,head
 def test_one_call_full_text_fixed_reference_and_seed(self):
  model,calls,head=self.fake_model()
  text='Sentence one, sentence two.\nSentence three? '*20
  audio,audit=continuous_generate(model,text,Path('teacher.wav'),1626)
  self.assertEqual(len(calls),1);self.assertEqual(calls[0]['text'],text)
  self.assertEqual(calls[0]['seed'],1626)
  self.assertEqual(calls[0]['reference_wav_path'],'teacher.wav')
  self.assertIsNone(calls[0]['prompt_wav_path']);self.assertFalse(calls[0]['retry_badcase'])
  self.assertTrue(audit['eos_observed']);self.assertTrue(head.removed)
 def test_does_not_deliver_length_capped_output(self):
  model,calls,head=self.fake_model(stop=0)
  with self.assertRaisesRegex(RuntimeError,'未正常结束'):continuous_generate(model,'Full script','teacher.wav',1)
  self.assertEqual(len(calls),1);self.assertTrue(head.removed)
 def test_context_overflow_fails_before_generation(self):
  model,calls,head=self.fake_model(tokens=8000)
  with self.assertRaisesRegex(ValueError,'上下文容量'):continuous_generate(model,'Long script','teacher.wav',1)
  self.assertFalse(calls)
 def test_old_unit_boundaries_are_ignored(self):
  request={'text':'whole original','reading_text':'whole reading','units':[{'reading_text':'a'},{'reading_text':'b'}]}
  self.assertEqual(generation_blocks(request),['whole reading'])
 def test_continuous_cache_cannot_reuse_old_segmented_request(self):
  old={'text':'Full text','language':'英语','seed':1}
  new=dict(old,generation_mode='continuous_full_text')
  self.assertNotEqual(request_fingerprint(old),request_fingerprint(new))
