import json,tempfile,unittest,wave
from pathlib import Path
import numpy as np
from cloud_voice_core import prepare_job
from voxcpm_kaggle_worker import profile_for,full_reading_prompt,request_fingerprint,process_audio
from voice_adjust import migrate_natural_pace,DEFAULT_NATURAL_STYLES

class NaturalPaceTests(unittest.TestCase):
 def test_migrate_fast_defaults_preserves_user_data_and_backup(self):
  settings=dict(tempo_by_language={'日语':1.5},generation_by_language={'日语':{'tempo':1.5,'gain_db':-2,'styles':['停顿短一点']}},last_audio='user.wav',prosody_templates={'日语':'jp.wav'},audio_history=[{'result':'old.wav'}])
  self.assertTrue(migrate_natural_pace(settings,['日语','英语']))
  self.assertEqual(settings['tempo_by_language']['日语'],1.0)
  self.assertEqual(settings['generation_by_language']['日语']['styles'],DEFAULT_NATURAL_STYLES)
  self.assertEqual(settings['generation_by_language']['日语']['gain_db'],-2)
  self.assertEqual(settings['pace_settings_before_natural_v1']['tempo_by_language']['日语'],1.5)
  self.assertEqual(settings['last_audio'],'user.wav');self.assertEqual(settings['prosody_templates']['日语'],'jp.wav')
  self.assertEqual(settings['audio_history'],[{'result':'old.wav'}])
 def test_migration_is_once_only(self):
  s={};migrate_natural_pace(s,['日语']);s['tempo_by_language']['日语']=.9
  self.assertFalse(migrate_natural_pace(s,['日语']));self.assertEqual(s['tempo_by_language']['日语'],.9)
 def test_srt_short_deadline_and_long_deadline_have_identical_model_input(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);requests=[]
   for end in ('00:00:00,100','00:10:00,000'):
    p=prepare_job(root/'jobs','member','owner/reference','1\n00:00:00,000 --> '+end+'\n自然に、優しく読みます。','日语',1626,root/'out')
    requests.append(json.loads((p.parent/'request.json').read_text()))
   a,b=requests;profile=profile_for('日语',1.0)
   self.assertEqual(full_reading_prompt(a,profile),full_reading_prompt(b,profile))
   self.assertEqual(request_fingerprint(a),request_fingerprint(b))
   self.assertIn('unhurried conversational pace',full_reading_prompt(a,profile))
   self.assertIn('natural breathing pauses',full_reading_prompt(a,profile))
   self.assertNotIn('-->',full_reading_prompt(a,profile))
   self.assertEqual(a['tempo'],1.0)
 def test_default_postprocess_does_not_squeeze_audio_to_subtitle_duration(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);src=root/'raw.wav';dst=root/'final.wav'
   with wave.open(str(src),'wb') as w:
    w.setparams((1,2,48000,0,'NONE','not compressed'))
    w.writeframes((np.sin(np.arange(96000)*2*np.pi*220/48000)*4000).astype('<i2').tobytes())
   report=process_audio(src,dst,1.0,0,False)
   self.assertAlmostEqual(report['final_seconds'],2.0,places=2)
   self.assertNotIn('rubberband',report['filter'])
