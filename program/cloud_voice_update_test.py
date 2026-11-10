import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import cloud_voice_update as update

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.root=self.base/'独立工具 with spaces';self.root.mkdir()
        self.env=patch.dict(os.environ,{'YANGNING_CLOUD_DATA_DIR':str(self.base/'private-data')});self.env.start()
        self.current={'name':update.PRODUCT,'version':'0.5-preview.1','update_sequence':5,'formal_studio_release':False,'source_revision':'a'*40}
        update.atomic_json(self.root/'preview_version.json',self.current)
        (self.root/'program').mkdir();(self.root/'program/cloud_voice_preview.py').write_text('old_program=True')
        self.old=(self.root/'program/cloud_voice_preview.py').read_bytes()
        (self.root/'program/templates').mkdir();(self.root/'program/templates/personal.wav').write_bytes(b'personal template')
        (self.root/'.preview_runtime').mkdir();(self.root/'.preview_runtime/user.marker').write_text('keep runtime')
        (self.base/'private-data').mkdir();(self.base/'private-data/settings.json').write_text('keep credentials references')
        self.version={**self.current,'version':'0.5-preview.2','update_sequence':6,'source_revision':'b'*40}
        self.files={name:(b'new_program=True\n' if name.endswith('.py') else b'new') for name in update.REQUIRED}
        self.files['preview_version.json']=json.dumps(self.version).encode()
        self.value={'product':update.PRODUCT,'sequence':6,'version':'0.5-preview.2','source_revision':'b'*40,
          'files':{name:{'content':base64.b64encode(data).decode(),'sha256':update.sha(data)} for name,data in self.files.items()}}
        self.data=json.dumps(self.value).encode()
        self.descriptor={'product':update.PRODUCT,'schema':1,'sequence':6,'version':'0.5-preview.2','source_revision':'b'*40,
             'payload_url':update.PREFIX+'c'*40+'/cloud_voice_payload.json','payload_size':len(self.data),'payload_sha256':update.sha(self.data),'notes':'Test update'}
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def fetch(self,url,limit):return json.dumps(self.descriptor).encode() if url==update.CHANNEL_URL else self.data
    def prepare(self):return update.prepare_update(self.root,self.descriptor,self.fetch,prepare_environment=False)
    def test_check_and_verified_apply_preserve_private_files(self):
        self.assertTrue(update.check_update(self.root,self.fetch)['available'])
        plan=self.prepare();update.apply_plan(plan,health_check=False)
        self.assertEqual(update.read_current(self.root)['version'],'0.5-preview.2')
        self.assertEqual((self.root/'program/templates/personal.wav').read_bytes(),b'personal template')
        self.assertEqual((self.root/'.preview_runtime/user.marker').read_text(),'keep runtime')
        self.assertEqual((self.base/'private-data/settings.json').read_text(),'keep credentials references')
        self.assertEqual(update.load_plan(plan)['status'],'awaiting_boot')
        update.restore(plan);self.assertEqual((self.root/'program/cloud_voice_preview.py').read_bytes(),self.old)
        self.assertFalse((self.root/'.runtime_selector.json').exists())
    def test_partial_failure_rolls_back_and_new_files_removed(self):
        plan=self.prepare()
        def fault(name):
            if name=='program/cloud_voice_preview.py':raise OSError('simulated disk failure')
        with self.assertRaises(OSError):update.apply_plan(plan,fault=fault,health_check=False)
        self.assertEqual(update.read_current(self.root),self.current)
        self.assertEqual((self.root/'program/cloud_voice_preview.py').read_bytes(),self.old)
        self.assertEqual(update.load_plan(plan)['status'],'rolled_back')
    def test_corruption_wrong_product_and_arbitrary_source_rejected(self):
        for descriptor in ({**self.descriptor,'payload_sha256':'0'*64},{**self.descriptor,'product':'Studio'},
                           {**self.descriptor,'payload_url':'https://evil.invalid/payload'},
                           {**self.descriptor,'payload_url':update.PREFIX+'main/cloud_voice_payload.json'}):
            with self.assertRaises(ValueError):update.validate_payload(self.data,descriptor)
        bad=copy.deepcopy(self.value);bad['files']['program/templates/private.wav']={'content':'','sha256':update.sha(b'')}
        data=json.dumps(bad).encode();desc={**self.descriptor,'payload_size':len(data),'payload_sha256':update.sha(data)}
        with self.assertRaises(ValueError):update.validate_payload(data,desc)
        self.assertEqual(update.read_current(self.root),self.current)
    def test_tampered_stage_rejected_without_mutation(self):
        plan=self.prepare();value=update.load_plan(plan)
        (Path(value['stage'])/'program/cloud_voice_preview.py').write_text('tampered=True')
        with self.assertRaises(ValueError):update.apply_plan(plan,health_check=False)
        self.assertEqual((self.root/'program/cloud_voice_preview.py').read_bytes(),self.old)
    def test_studio_root_and_same_version_are_not_updated(self):
        update.atomic_json(self.root/'preview_version.json',{**self.current,'formal_studio_release':True})
        with self.assertRaises(ValueError):update.check_update(self.root,self.fetch)
        update.atomic_json(self.root/'preview_version.json',self.current)
        desc={**self.descriptor,'sequence':5,'version':'0.5-preview.1'}
        self.assertFalse(update.check_update(self.root,lambda url,limit:json.dumps(desc).encode())['available'])
        with self.assertRaises(ValueError):update.prepare_update(self.root,desc,self.fetch,False)
    def test_future_python_module_can_update_but_template_or_runtime_cannot(self):
        value=copy.deepcopy(self.value)
        content=b"new_feature=True\n"
        value["files"]["program/future_feature.py"]={"content":base64.b64encode(content).decode(),"sha256":update.sha(content)}
        data=json.dumps(value).encode();desc={**self.descriptor,"payload_size":len(data),"payload_sha256":update.sha(data)}
        self.assertIn("program/future_feature.py",update.validate_payload(data,desc))
        for name in ("program/templates/private.wav",".preview_runtime/python.exe","../outside.py","program/../outside.py","program/settings.json"):
            self.assertFalse(update.allowed_file(name))

    def test_boot_ack_requires_correct_transaction_root(self):
        plan=self.prepare();update.apply_plan(plan,health_check=False)
        with patch.dict(os.environ,{'YANGNING_UPDATE_PLAN':str(plan)}):update.acknowledge_boot(self.root)
        value=update.load_plan(plan)
        self.assertEqual(json.loads((Path(value['tx'])/'boot_ok.json').read_text())['version'],'0.5-preview.2')
        with self.assertRaises(ValueError):update.apply_plan(plan,health_check=False)

if __name__=='__main__':unittest.main()
