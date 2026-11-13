import base64,hashlib,importlib.util,json,os,shutil,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import cloud_voice_update as updater
from cloud_voice_core import prepare_job,run_job
from local_voice import LocalEngine

class UpdateReleaseTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.base=Path(self.temp.name);self.root=self.base/'install';self.root.mkdir()
  self.env=patch.dict(os.environ,{'YANGNING_CLOUD_DATA_DIR':str(self.base/'data')});self.env.start();self.addCleanup(self.env.stop)
  self.product=updater.PRODUCT
  (self.root/'preview_version.json').write_text(json.dumps(dict(name=self.product,formal_studio_release=False,version='0.6-preview.1',update_sequence=8)))
  self.revision='a'*40
  source=Path(__file__).parent.parent
  files={}
  for p in source.rglob('*'):
   name=p.relative_to(source).as_posix()
   if p.is_file() and updater.allowed_file(name):
    content=p.read_bytes()
    if name=='preview_version.json':
     v=json.loads(content);v['source_revision']=self.revision;content=json.dumps(v).encode()
    files[name]=dict(content=base64.b64encode(content).decode(),sha256=hashlib.sha256(content).hexdigest())
  meta=dict(product=self.product,sequence=14,version='0.7-preview.6',source_revision=self.revision)
  self.payload=json.dumps(dict(meta,files=files)).encode()
  self.descriptor=dict(meta,schema=1,payload_url=updater.PREFIX+self.revision+'/cloud_voice_payload.json',payload_size=len(self.payload),payload_sha256=hashlib.sha256(self.payload).hexdigest(),notes='test')
 def fetch(self,url,limit):return json.dumps(self.descriptor).encode() if url==updater.CHANNEL_URL else self.payload
 def test_detect_verify_stage_apply_preserves_user_files(self):
  for name in ('settings.json','program/references/teacher_reference.wav','program/templates/custom.wav','model_cache/weights.bin'):
   p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'private user content')
  self.assertTrue(updater.check_update(self.root,self.fetch)['available'])
  plan=updater.prepare_update(self.root,self.descriptor,self.fetch,prepare_environment=False)
  updater.apply_plan(plan,health_check=False)
  self.assertEqual(updater.read_current(self.root)['update_sequence'],14)
  for name in ('settings.json','program/references/teacher_reference.wav','program/templates/custom.wav','model_cache/weights.bin'):
   self.assertEqual((self.root/name).read_bytes(),b'private user content')
 def test_corrupt_download_does_not_modify_install(self):
  original=(self.root/'preview_version.json').read_bytes()
  with self.assertRaises(ValueError):updater.prepare_update(self.root,self.descriptor,lambda *a:b'bad',prepare_environment=False)
  self.assertEqual((self.root/'preview_version.json').read_bytes(),original)
 def test_apply_failure_rolls_back(self):
  original=(self.root/'preview_version.json').read_bytes()
  plan=updater.prepare_update(self.root,self.descriptor,self.fetch,prepare_environment=False)
  def fail(name):raise OSError('simulated disk failure')
  with self.assertRaises(OSError):updater.apply_plan(plan,health_check=False,fault=fail)
  self.assertEqual((self.root/'preview_version.json').read_bytes(),original)
 def test_cancel_before_cloud_submission(self):
  event=threading.Event();event.set()
  job=prepare_job(self.base/'jobs','member','owner/reference','测试。','英语',1,self.base/'out')
  calls=[]
  with self.assertRaisesRegex(RuntimeError,'停止等待'):
   run_job(job,'not-a-real-token',lambda event:None,cli=lambda *a,**k:calls.append(a),cancel_event=event)
  self.assertFalse(calls)
 def test_cancel_before_local_process(self):
  event=threading.Event();event.set();engine=LocalEngine()
  with self.assertRaisesRegex(RuntimeError,'已取消'):engine.execute('unused.json',lambda event:None,cancel_event=event)
  self.assertIsNone(engine.process)
