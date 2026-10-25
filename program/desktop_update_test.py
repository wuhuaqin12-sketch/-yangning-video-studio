"""Update integrity, interrupted installs and hostile archives."""
import hashlib,json,stat,tempfile,unittest,zipfile
from pathlib import Path
from desktop_update import *

def package(path,version='0.12.0',extra=None):
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('release.json',json.dumps(dict(app='YangNingStudio',schema=1,version=version)))
        for name in ('app.py','bootstrap.py','desktop_update.py','desktop_launch.py','requirements.txt'):
            z.writestr('program/'+name,'# release\n')
        for name,value in (extra or {}).items():z.writestr(name,value)

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.p=Path(self.temp.name);self.root=self.p/'installed';self.z=self.p/'release.zip'
        package(self.z)
    def test_staging_does_not_switch_until_activation(self):
        v,path=stage_package(self.z,self.root)
        self.assertFalse((self.root/'current.json').exists())
        activate(self.root,v)
        self.assertEqual(json.loads((self.root/'current.json').read_text())['version'],v)
        package(self.z,'0.13.0');v,path=stage_package(self.z,self.root);activate(self.root,v)
        data=json.loads((self.root/'current.json').read_text())
        self.assertEqual(data['previous_version'],'0.12.0')
        activate(self.root,data['previous_version'])
        self.assertEqual(json.loads((self.root/'current.json').read_text())['version'],'0.12.0')
    def test_duplicate_version_keeps_installed_files(self):
        stage_package(self.z,self.root)
        with self.assertRaises(ValueError):stage_package(self.z,self.root)
        self.assertTrue((self.root/'versions/0.12.0/program/app.py').is_file())
    def test_rejects_paths_and_windows_aliases(self):
        for name in ('../escape.py','/absolute.py','program/../../escape.py','C:/bad.py','program\\bad.py','program/CON.txt','program/file.','program/file:stream'):
            package(self.z,extra={name:'bad'})
            with self.assertRaises(ValueError,msg=name):stage_package(self.z,self.root)
            self.assertFalse((self.p/'escape.py').exists())
            self.assertFalse(list((self.root/'versions').glob('.staging-*')))
    def test_rejects_symlinks(self):
        with zipfile.ZipFile(self.z,'a') as z:
            i=zipfile.ZipInfo('program/link');i.create_system=3;i.external_attr=(stat.S_IFLNK|0o777)<<16
            z.writestr(i,'../../escape')
        with self.assertRaises(ValueError):stage_package(self.z,self.root)
    def test_manifest_version_mismatch_keeps_pointer(self):
        v,_=stage_package(self.z,self.root);activate(self.root,v)
        before=(self.root/'current.json').read_bytes()
        with self.assertRaises(ValueError):stage_package(self.z,self.root,'0.99.0')
        self.assertEqual((self.root/'current.json').read_bytes(),before)
    def test_verified_download_and_wrong_digest(self):
        payload=self.z.read_bytes()
        info=dict(version='0.12.0',url='https://example.org/release.zip',sha256=hashlib.sha256(payload).hexdigest(),size=len(payload))
        def loader(url,limit,path):Path(path).write_bytes(payload)
        with self.assertRaises(ValueError):download_update({**info,'sha256':'0'*64},self.root,loader)
        self.assertFalse((self.root/'versions/0.12.0').exists())
        with self.assertRaises(ValueError):download_update({**info,'size':1},self.root,loader)
        version,target=download_update(info,self.root,loader)
        self.assertEqual(version,'0.12.0');self.assertTrue(target.is_dir())
        self.assertFalse((self.root/'current.json').exists())
    def test_cancelled_download_keeps_current_version(self):
        import threading
        from unittest.mock import patch
        import io
        from media import Cancelled
        cancel=threading.Event();cancel.set()
        class Response(io.BytesIO):
            url='https://example.org/release.zip'
        class Opener:
            def open(self,*args,**kwargs):return Response(b'payload')
        with patch('urllib.request.build_opener',return_value=Opener()):
            with self.assertRaises(Cancelled):fetch('https://example.org/release.zip',1024,self.p/'download.zip',cancel)
    def test_config_and_release_check(self):
        self.assertIsNone(check_update(self.root))
        save_config('https://example.org/latest.json',self.root)
        major,minor,patch=map(int,APP_VERSION.split('.'))
        newer=f'{major}.{minor}.{patch+1}'
        data=dict(format='YangNingStudioUpdate',schema=1,version=newer,url='https://example.org/app.zip',sha256='a'*64,size=100,notes='Fix')
        self.assertEqual(check_update(self.root,lambda *_:json.dumps(data).encode())['version'],newer)
        data['version']=APP_VERSION
        self.assertEqual(check_update(self.root,lambda *_:json.dumps(data).encode()),{})
        data['url']='http://example.org/app.zip'
        with self.assertRaises(ValueError):check_update(self.root,lambda *_:json.dumps(data).encode())
    def test_publisher_bundle_matches_manifest_and_version(self):
        import subprocess,sys
        helper=Path(__file__).resolve().parent.parent/'make_release.py'
        subprocess.run([sys.executable,str(helper),'--version','0.12.3',
                        '--package-url','https://example.org/app.zip',
                        '--manifest-url','https://example.org/latest.json',
                        '--output',str(self.p/'published')],check=True,capture_output=True)
        manifest=json.loads((self.p/'published/latest.json').read_text())
        archive=self.p/'published/YangNing_VideoStudio_Windows_0.12.3.zip'
        self.assertEqual(manifest['sha256'],hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertEqual(manifest['size'],archive.stat().st_size)
        with zipfile.ZipFile(archive) as z:
            self.assertIn(b"APP_VERSION='0.12.3'",z.read('program/desktop_update.py'))
            self.assertIn(b"VERSION='0.12.3'",z.read('program/engine.py'))
            self.assertEqual(json.loads(z.read('release.json'))['update_manifest_url'],'https://example.org/latest.json')
            self.assertFalse(any('__pycache__' in n or '.venv/' in n for n in z.namelist()))
        version,target=stage_package(archive,self.root,'0.12.3')
        self.assertEqual(version,'0.12.3')

    def test_invalid_version_and_url(self):
        for value in ('../oops','1','1.0.0/dev',None):
            with self.assertRaises(ValueError):version_tuple(value)
        for value in ('http://example.org/a','file:///a','https://user:pass@example.org/x','https://example.org/x#f'):
            with self.assertRaises(ValueError):https_url(value)

if __name__=='__main__':unittest.main(verbosity=2)
