import hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import stable_recovery as r
from desktop_update import atomic_json

class StableRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name);self.root=self.p/'app';self.settings=self.p/'settings'
        self.settings.mkdir();self.root.mkdir()
        self.archive=self.p/'stable.zip'
        with zipfile.ZipFile(self.archive,'w') as z:
            z.writestr('release.json',json.dumps({'app':'YangNingStudio','schema':1,'version':r.STABLE_VERSION}))
            for n in ('app.py','bootstrap.py','desktop_update.py','desktop_launch.py','requirements.txt'):
                z.writestr('program/'+n,'# stable\n')
        self.patchers=[patch.object(r,'STABLE_SIZE',self.archive.stat().st_size),patch.object(r,'STABLE_SHA256',r.digest(self.archive))]
        for p in self.patchers:p.start();self.addCleanup(p.stop)
        atomic_json(self.root/'current.json',{'version':'0.12.11'})
        atomic_json(self.settings/'style_no_denoise.json',{'stable':True})
        self.stable_backup=r.snapshot(self.root,self.settings)
        atomic_json(self.root/'current.json',{'version':'0.12.15'})
        atomic_json(self.settings/'style_no_denoise.json',{'new':True})
        self.media=self.settings/'precious-video.mp4';self.media.write_bytes(b'do not change')
    def test_archive_validation_does_not_claim_windows_pass(self):
        report=r.verify_archive(self.archive)
        self.assertTrue(report['archive_verified']);self.assertFalse(report['windows_launch_verified'])
    def test_corrupt_archive_keeps_current_and_settings(self):
        self.archive.write_bytes(b'broken')
        with self.assertRaises(ValueError):r.preserve_archive(self.root,self.archive)
        self.assertEqual(json.loads((self.root/'current.json').read_text())['version'],'0.12.15')
        self.assertFalse((self.root/'protected/v0.12.11-original.zip').exists())
    def test_failed_healthcheck_preserves_pointer_and_settings(self):
        before=(self.root/'current.json').read_bytes();config=(self.settings/'style_no_denoise.json').read_bytes()
        with self.assertRaises(RuntimeError):r.restore(self.root,self.settings,self.archive,lambda _:dict(platform='linux',passed=True),self.stable_backup)
        self.assertEqual((self.root/'current.json').read_bytes(),before)
        self.assertEqual((self.settings/'style_no_denoise.json').read_bytes(),config)
        self.assertTrue(self.media.exists())
    def test_missing_compatible_config_blocks_activation(self):
        with self.assertRaisesRegex(RuntimeError,'配置快照'):r.restore(self.root,self.settings,self.archive,lambda _:dict(platform='win32',passed=True))
        self.assertEqual(json.loads((self.root/'current.json').read_text())['version'],'0.12.15')
    def test_restore_preserves_media_newer_program_and_newer_config_backup(self):
        newer=self.root/'versions/0.12.15/program';newer.mkdir(parents=True);(newer/'app.py').write_text('new')
        r.restore(self.root,self.settings,self.archive,lambda _:dict(platform='win32',passed=True),self.stable_backup)
        self.assertEqual(json.loads((self.root/'current.json').read_text())['version'],r.STABLE_VERSION)
        self.assertEqual(json.loads((self.settings/'style_no_denoise.json').read_text()),{'stable':True})
        self.assertEqual(self.media.read_bytes(),b'do not change');self.assertTrue((newer/'app.py').exists())
        values=[json.loads(f.read_text()) for f in (self.root/'backups').glob('*/settings/style_no_denoise.json')]
        self.assertIn({'new':True},values)
    def test_modified_installed_stable_not_overwritten(self):
        target=r.stage_stable(self.root,self.archive);(target/'program/app.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'不一致'):r.stage_stable(self.root,self.archive)
        self.assertEqual((target/'program/app.py').read_text(),'changed')
    def test_tampered_snapshot_rejected(self):
        (self.stable_backup/'settings/style_no_denoise.json').write_text('{}')
        with self.assertRaises(ValueError):r.validate_snapshot(self.stable_backup)
    def test_snapshot_never_copies_media_or_outputs(self):
        b=r.snapshot(self.root,self.settings)
        self.assertFalse(list(b.rglob('*.mp4')))
        self.assertEqual({v['path'] for v in r.validate_snapshot(b)['files']},{'install/current.json','settings/style_no_denoise.json'})
if __name__=='__main__':unittest.main()
