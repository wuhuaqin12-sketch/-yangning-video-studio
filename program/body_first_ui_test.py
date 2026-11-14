"""Exercise visibility and state preservation on a real Tk display."""
import os,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch

@unittest.skipUnless(os.name=='nt' or os.environ.get('DISPLAY'),'Needs a real Tk display')
class BodyFirstUITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.folder=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'LOCALAPPDATA':str(self.folder),'YANGNING_DATA_ROOT':str(self.folder/'profile'),'YANGNING_INSTALL_ROOT':''});self.env.start();self.addCleanup(self.env.stop)
        import tkinter as tk,app
        data=self.folder/'data';data.mkdir()
        self.data_patch=patch.object(app,'DATA',data);self.data_patch.start();self.addCleanup(self.data_patch.stop)
        self.state_patch=patch.object(app,'STATE',data/'queue.json');self.state_patch.start();self.addCleanup(self.state_patch.stop)
        self.root=tk.Tk();self.app=app.App(self.root);self.panel=self.app.sequence_panel;self.panel.restoring=False;self.root.update()
    def tearDown(self):
        for timer in self.root.tk.call('after','info'):
            try:self.root.after_cancel(timer)
            except Exception:pass
        self.root.destroy()
    def mode(self,index):
        from next_ui import SEGMENT_MODES
        self.panel.segment_mode.set(SEGMENT_MODES[index]);self.panel.change_segments();self.root.update()
    def test_default_body_is_compact_and_classic_flow_stays_available(self):
        p=self.panel
        self.assertFalse(p.enabled.get());self.assertFalse(self.app.sequence_settings)
        for part in (p.controls,p.segments,p.intro,p.outro,p.combined,p.music,self.app.activity):self.assertFalse(part.winfo_ismapped())
        self.assertFalse(self.app.v['burn'].get())
        self.assertEqual(p.layout_vars['landscape']['subtitle_font_size'].get(),'84')
        self.assertEqual(p.layout_vars['portrait']['subtitle_font_size'].get(),'')
        self.assertEqual(p.layout_vars['landscape']['repair_method'].get(),'glyph')
        self.app.v['video'].set('ordinary.mp4');self.root.update();self.assertFalse(p.enabled.get())
        self.assertLess(self.app.main_button.winfo_rooty()+self.app.main_button.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
        self.assertTrue(callable(self.app.advanced));self.assertTrue(callable(self.app.timing_settings));self.assertTrue(callable(self.app.final_export))
    def test_modes_show_only_relevant_fields_and_preserve_disabled_assets(self):
        p=self.panel;self.mode(1)
        self.assertTrue(p.segment_switch.winfo_ismapped());self.assertFalse(p.intro.winfo_ismapped());self.assertFalse(p.outro.winfo_ismapped())
        p.v['intro_enabled'].set(True);p.v['outro_enabled'].set(True);p.v['intro_mode'].set('external_music');p.update();self.root.update()
        self.assertTrue(p.intro.winfo_ismapped());self.assertTrue(p.outro.winfo_ismapped());self.assertTrue(p.music.winfo_ismapped())
        p.v['background_audio'].set('keep-this-music.wav')
        self.mode(2);self.assertTrue(p.combined.winfo_ismapped());self.assertFalse(p.intro.winfo_ismapped());self.assertFalse(p.outro.winfo_ismapped())
        self.assertEqual(self.app.media_labels['video'].cget('text'),'完整视频 MP4');self.assertTrue(p.value()['combined']);self.assertFalse(p.value()['outro_enabled'])
        self.mode(0);self.assertFalse(p.segments.winfo_ismapped());self.assertFalse(p.value()['combined']);self.assertFalse(p.value()['intro_enabled']);self.assertFalse(p.value()['outro_enabled']);self.assertEqual(p.value()['background_audio'],'')
        self.assertEqual(p.v['background_audio'].get(),'keep-this-music.wav');self.assertTrue(p.v['intro_enabled'].get())
        self.mode(1);self.assertEqual(p.value()['background_audio'],'keep-this-music.wav')
    def test_saved_ui_preferences_restore_and_old_projects_migrate(self):
        from project_vnext import save_project
        p=self.panel;self.mode(1);p.v['intro_enabled'].set(True);p.v['intro_mode'].set('external_music')
        music=self.folder/'music.wav';music.write_bytes(b'test-path-only');p.v['background_audio'].set(str(music));p.appearance_open.set(True);p.update()
        job=p.project();saved=self.folder/'project.json';save_project(saved,job)
        self.mode(0);p.v['background_audio'].set('');p.appearance_open.set(False);p.load(saved);self.root.update()
        self.assertEqual(p.segment_mode.get(),'另加片头 / 片尾');self.assertEqual(p.v['background_audio'].get(),str(music));self.assertTrue(p.appearance_open.get())
        job.pop('ui_state');job['sequence'].update(combined=True,intro_enabled=False,outro_enabled=False,background_audio='');save_project(saved,job);p.load(saved);self.root.update()
        self.assertEqual(p.segment_mode.get(),'整片视频（已有片头片尾）')
    def test_optional_title_and_disclaimer_dialog_preserves_defaults(self):
        import tkinter as tk
        p=self.panel;p.decoration_settings();self.root.update()
        dialog=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel))
        self.assertFalse(p.v['opening_title_enabled'].get());self.assertFalse(p.v['disclaimer_enabled'].get())
        p.v['disclaimer_enabled'].set(True);self.root.update()
        self.assertTrue(p.enabled.get());self.assertTrue(p.value()['disclaimer_enabled'])
        p.v['disclaimer_mode'].set('overlay');p.v['disclaimer_seconds'].set('8')
        self.assertEqual(p.project()['sequence']['disclaimer_seconds'],8)
        self.assertEqual(p.project()['sequence']['disclaimer_mode'],'overlay')
        p.v['disclaimer_seconds'].set('')
        with self.assertRaises(ValueError):self.app.settings()
        p.v['disclaimer_seconds'].set('8')
        dialog.destroy()
if __name__=='__main__':unittest.main()
