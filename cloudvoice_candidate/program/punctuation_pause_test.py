import copy,json,tempfile,unittest,wave
from pathlib import Path
from unittest.mock import patch
import numpy as np
from punctuation_pause import phrases,alignment_words,insert_pauses,repair_file,POLICY
from cloud_voice_core import prepare_job,build_notebook,deliver_result
from voxcpm_kaggle_worker import generation_blocks,request_fingerprint,process_audio

class PunctuationPauseTests(unittest.TestCase):
 def fixture(self):
  rate=16000
  # Three voiced words with measured 100ms / 200ms quiet gaps.
  x=np.zeros(rate*3,dtype=np.float32)
  for a,b in ((.1,.7),(.8,1.5),(1.7,2.5)):
   x[round(a*rate):round(b*rate)]=.2*np.sin(np.arange(round((b-a)*rate))*2*np.pi*220/rate)
  ss=[dict(start=a,end=b,confidence=.9) for a,b in ((.1,.7),(.8,1.5),(1.7,2.5))]
  rs=[dict(text=t,first_word=i,last_word=i,minimum_seconds=p) for i,(t,p) in enumerate((('one',.3),('two',.6),('three',0)))]
  return x,rate,rs,ss
 def test_comma_period_and_newline(self):
  r=phrases('first, second.\nthird? fourth。第五、最後。')
  self.assertEqual([p['minimum_seconds'] for p in r],[.3,.7,.6,.6,.3,.6])
 def test_numbers_and_abbreviations_are_not_false_pauses(self):
  self.assertEqual([p['text'] for p in phrases('Dr. Smith paid 1,000 dollars, at 3.14 pm. Then left.')],['Dr. Smith paid 1,000 dollars','at 3.14 pm','Then left'])
  self.assertEqual([p['text'] for p in phrases('T. rex lived here. I. Then left.')],['T. rex lived here','I','Then left'])
 def test_minimum_pause_no_speed_or_sample_loss(self):
  x,sr,rs,ss=self.fixture(); before=x.copy()
  y,r=insert_pauses(x,sr,rs,ss)
  self.assertTrue(np.array_equal(x,before))
  self.assertAlmostEqual(r['added_seconds'],.6,delta=.02)
  self.assertEqual(len(y),len(x)+sum(e['added_samples'] for e in r['boundaries']))
  self.assertEqual(r['model_calls_for_speech'],0)
  # Everything outside the explicit 3ms boundary fades is bit-identical.
  a=0;offset=0;fade=round(.003*sr)
  for e in r['boundaries']:
   cut=e['source_sample'];self.assertTrue(np.array_equal(x[a+fade:cut-fade],y[a+offset+fade:cut+offset-fade]))
   self.assertTrue(np.all(y[cut+offset:cut+offset+e['added_samples']]==0))
   a=cut;offset+=e['added_samples']
  self.assertTrue(np.array_equal(x[a+fade:],y[a+offset+fade:]))
 def test_existing_long_silence_is_not_added_again(self):
  x,sr,rs,ss=self.fixture();rs[0]['minimum_seconds']=.05;rs[1]['minimum_seconds']=.1
  y,r=insert_pauses(x,sr,rs,ss)
  self.assertEqual(r['added_seconds'],0);self.assertTrue(np.array_equal(x,y))
 def test_real_wav_repair_then_ffmpeg_preserves_longer_duration(self):
  import soundfile as sf
  x,sr,rs,ss=self.fixture()
  with tempfile.TemporaryDirectory() as d:
   raw,paused,final=[Path(d)/n for n in ('raw.wav','paused.wav','final.wav')]
   sf.write(raw,x,sr,subtype='PCM_16')
   original=raw.read_bytes()
   with patch('punctuation_pause.acoustic_alignment',return_value=ss):
    audit=repair_file(raw,paused,'one, two. three.','英语')
   report=process_audio(paused,final,1.0,0.0,False)
   self.assertAlmostEqual(report['final_seconds'],3+audit['added_seconds'],delta=.002)
   with wave.open(str(final),'rb') as w:self.assertEqual(w.getframerate(),48000)
   self.assertEqual(raw.read_bytes(),original)
 def test_no_internal_boundary_avoids_alignment_download(self):
  with patch('punctuation_pause.acoustic_alignment',side_effect=AssertionError('must not download')):
   self.assertIsNone(repair_file('unused.wav','unused-output.wav','One short sentence.','英语'))
 def test_low_confidence_or_invalid_order_fails_before_edit(self):
  x,sr,rs,ss=self.fixture();before=x.copy();ss[1]['confidence']=.1
  with self.assertRaisesRegex(ValueError,'可信度'):insert_pauses(x,sr,rs,ss)
  self.assertTrue(np.array_equal(x,before))
  ss[1]['confidence']=.9;ss[1]['start']=.6
  with self.assertRaises(ValueError):insert_pauses(x,sr,rs,ss)
 def test_six_language_normalization_keeps_numbers_and_phrase_mapping(self):
  samples={'日语':'静かに、三つの言葉を読みます。次へ。','英语':'We have 3 apples, and 2 pears. Read gently.',
   '法语':'Nous avons 3 pommes, et 2 poires. Lisez doucement.', '德语':'Wir haben 3 Äpfel, und 2 Birnen. Bitte ruhig lesen.',
   '印尼语':'Kami punya 3 apel, dan 2 pir. Bacalah perlahan.', '粤语':'我哋有3個蘋果，同2個梨。請慢慢讀。'}
  for language,text in samples.items():
   with self.subTest(language=language):
    words,rs=alignment_words(phrases(text),language)
    self.assertTrue(words);self.assertEqual(rs[-1]['last_word'],len(words)-1)
    self.assertFalse(any(any(c.isdigit() for c in w) for w in words))
    if language=='英语':self.assertIn('three',words);self.assertIn('two',words)
    if language=='印尼语':self.assertIn('tiga',words);self.assertIn('dua',words)
 def test_new_job_and_cloud_notebook_include_same_module(self):
  with tempfile.TemporaryDirectory() as d:
   p=prepare_job(Path(d)/'jobs','member','owner/ref','Hello, world. Read gently.','英语',1,Path(d)/'out')
   r=json.loads((p.parent/'request.json').read_text());m=json.loads(p.read_text())
   self.assertEqual(r['punctuation_pause_policy'],POLICY);self.assertEqual(m['punctuation_pause_policy'],POLICY)
   self.assertEqual(len(generation_blocks(r)),1)
   nb=build_notebook(r);source=''.join(nb['cells'][-1]['source'])
   self.assertIn("types.ModuleType('punctuation_pause')",source)
   self.assertIn('repair_file(raw_path,pause_path,spoken_text',source)
   for cell in nb['cells']:
    if cell['cell_type']=='code':compile(''.join(cell['source']),'notebook','exec')
   old=copy.deepcopy(r);old.pop('punctuation_pause_policy')
   self.assertNotEqual(request_fingerprint(old),request_fingerprint(r))
