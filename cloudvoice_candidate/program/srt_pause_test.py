import io,json,tempfile,unittest,wave
from pathlib import Path
from array import array
from cloud_voice_core import parse_srt_cues,prepare_job
from voxcpm_kaggle_worker import assemble_timed_audio,pause_units,natural_pause,request_fingerprint

class PauseTests(unittest.TestCase):
 def assemble(self,lengths,cues=None,pauses=None,tempo=1):
  out=io.BytesIO()
  with wave.open(out,'wb') as w:
   w.setparams((1,2,1000,0,'NONE','not compressed'))
   segments,warnings,total=assemble_timed_audio(w,[array('h',[100])*n for n in lengths],1000,cues,pauses,tempo)
  with wave.open(io.BytesIO(out.getvalue()),'rb') as w: self.assertEqual(w.getnframes(),total)
  return segments,warnings,total
 def test_parse_index_multiline_bom(self):
  cues=parse_srt_cues('\ufeff7\r\n00:00:01,000 --> 00:00:03,500\r\n第一行\r\n第二行')
  self.assertEqual(cues,[dict(index=7,start=1,end=3.5,text='第一行 第二行')])
 def test_reject_invalid(self):
  for s in ['x\n00:00:01,000 --> 00:00:02,000\na','1\n00:00:01,000 --> 00:00:00,000\na','1\n00:65:00,000 --> 01:00:00,000\na']:
   with self.assertRaises(ValueError): parse_srt_cues(s)
 def test_absolute_starts_and_tail(self):
  seg,w,total=self.assemble([500,400],[dict(index=1,start=2,end=3),dict(index=2,start=5,end=6)])
  self.assertEqual(seg,[dict(start=2,end=2.5),dict(start=5,end=5.4)])
  self.assertEqual(total,6000);self.assertFalse(w)
 def test_overflow_never_truncates(self):
  seg,w,total=self.assemble([2500,500],[dict(index=8,start=0,end=1),dict(index=9,start=1.5,end=2)])
  self.assertEqual(seg[1]['start'],2.5);self.assertEqual(total,3000);self.assertEqual(w[0]['index'],8)
  self.assertEqual(w[0]['overflow_seconds'],1.5)
 def test_long_gap_not_capped(self):
  seg,w,total=self.assemble([100,100],[dict(index=1,start=45,end=46),dict(index=2,start=100,end=101)])
  self.assertEqual(seg[0]['start'],45);self.assertEqual(seg[1]['start'],100);self.assertEqual(total,101000)
 def test_tempo_preserves_final_cue_start(self):
  seg,w,total=self.assemble([100,100],[dict(start=1,end=2),dict(start=4,end=5)],tempo=2)
  self.assertEqual(seg[1]['start'],4);self.assertEqual(total,10000)
 def test_txt_punctuation_and_newlines(self):
  self.assertEqual(pause_units('你好，世界。好吗？\n下一句'),['你好，','世界。','好吗？','下一句'])
  seg,w,total=self.assemble([100,100,100],pauses=[.22,.45,.45])
  self.assertEqual(total,970);self.assertEqual(seg[2]['start'],.87)
 def test_timing_metadata_does_not_change_natural_generation(self):
  a=dict(language='英语',text='hello',srt_cues=[dict(start=1,end=2)])
  b=dict(a,srt_cues=[dict(start=2,end=3)])
  self.assertEqual(request_fingerprint(a),request_fingerprint(b))
if __name__=='__main__':unittest.main()
