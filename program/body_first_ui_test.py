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
        self.assertFalse(p.opening_text_button.winfo_ismapped())
        self.assertTrue(p.segment_mode_box.winfo_ismapped());self.assertEqual(p.segment_mode_box.master,self.app.material_mode_row)
        self.assertTrue(p.output_mode_box.winfo_ismapped())
        self.assertEqual(p.segments.master,self.app.segment_host)
        for part in (p.controls,p.segments,p.intro,p.outro,p.combined,p.music,self.app.activity):self.assertFalse(part.winfo_ismapped())
        self.assertFalse(self.app.v['burn'].get())
        self.assertEqual(self.app.v['speed'].get(),'1.0')
        self.assertEqual(self.app.language_name.get(),'按文件名判断')
        self.assertEqual(p.layout_vars['landscape']['subtitle_font_size'].get(),'84')
        self.assertEqual(p.layout_vars['portrait']['subtitle_font_size'].get(),'')
        self.assertEqual(p.layout_vars['landscape']['repair_method'].get(),'glyph')
        self.assertTrue(p.layout_vars['landscape']['repair_full_width'].get())
        self.app.v['video'].set('ordinary.mp4');self.root.update();self.assertFalse(p.enabled.get())
        self.assertLess(self.app.main_button.winfo_rooty()+self.app.main_button.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
        self.assertTrue(callable(self.app.advanced));self.assertTrue(callable(self.app.timing_settings));self.assertTrue(callable(self.app.final_export))
    def test_modes_show_only_relevant_fields_and_preserve_disabled_assets(self):
        p=self.panel;self.mode(1)
        self.assertTrue(p.segment_switch.winfo_ismapped());self.assertFalse(p.intro.winfo_ismapped());self.assertFalse(p.outro.winfo_ismapped())
        self.assertFalse(p.opening_text_button.winfo_ismapped())
        p.v['intro_enabled'].set(True);p.v['outro_enabled'].set(True);p.v['intro_mode'].set('external_music');p.update();self.root.update()
        self.assertTrue(p.intro.winfo_ismapped());self.assertTrue(p.outro.winfo_ismapped());self.assertTrue(p.music.winfo_ismapped())
        p.v['background_audio'].set('keep-this-music.wav')
        self.mode(2);self.assertTrue(p.combined.winfo_ismapped());self.assertFalse(p.intro.winfo_ismapped());self.assertFalse(p.outro.winfo_ismapped())
        self.assertFalse(p.diamond_enabled.get());self.assertFalse(p.opening_text_button.winfo_ismapped())
        self.assertFalse(p.value()['combined']);self.assertEqual(p.value()['background_audio'],'')
        p.diamond_enabled.set(True);p.update();self.root.update()
        self.assertTrue(p.opening_text_button.winfo_ismapped())
        self.assertEqual(p.opening_text_button.master,p.diamond_details)
        self.assertEqual(self.app.media_labels['video'].cget('text'),'完整视频 MP4');self.assertTrue(p.value()['combined']);self.assertFalse(p.value()['outro_enabled'])
        self.mode(0);self.assertFalse(p.segments.winfo_ismapped());self.assertFalse(p.value()['combined']);self.assertFalse(p.value()['intro_enabled']);self.assertFalse(p.value()['outro_enabled']);self.assertEqual(p.value()['background_audio'],'')
        self.assertEqual(p.v['background_audio'].get(),'keep-this-music.wav');self.assertTrue(p.v['intro_enabled'].get())
        self.mode(1);self.assertEqual(p.value()['background_audio'],'keep-this-music.wav')
    def test_language_ending_selection_never_keeps_previous_language(self):
        p=self.panel;self.mode(2);p.diamond_enabled.set(True);p.v['combined_replace_outro'].set(True);p.update();self.root.update()
        self.assertTrue(p.replacement.winfo_ismapped())
        paths={code:self.folder/(code+'.mp4') for code in ('ja','en','fr','de','yue','id')}
        with patch('ending_presets.load_preset',side_effect=lambda root,code:paths.get(code)):
            for code in ('en','fr','de','yue','id','ja'):
                self.app.v['language'].set(code);self.assertEqual(p.v['outro_video'].get(),str(paths[code]))
            self.app.v['language'].set('es');self.assertEqual(p.v['outro_video'].get(),'')
        p.v['combined_outro_start'].set('120');self.app.v['language'].set('id')
        self.assertEqual(p.v['combined_outro_start'].get(),'120')
        self.mode(0);self.assertFalse(p.value()['combined_replace_outro'])
        self.mode(2);self.assertTrue(p.value()['combined_replace_outro'])

    def test_title_preview_does_not_require_outro_audio_or_srt_or_approve_full_export(self):
        p=self.panel;self.mode(2);p.diamond_enabled.set(True);p.v['opening_title_enabled'].set(True)
        self.app.language_name.set('日语');self.app.language_changed();self.app.v['video'].set('fixture_only.mp4')
        self.assertEqual(p.v['combined_outro_start'].get(),'0');self.assertEqual(self.app.v['source_srt'].get(),'')
        p.approved_preview='unchanged';p.decoration_settings();self.root.update()
        with patch.object(self.app,'settings',side_effect=AssertionError('Must not request full export inputs')),patch.object(self.app,'worker') as worker:
            p.preview_title('opening_title');self.assertTrue(worker.called)
        self.assertEqual(p.approved_preview,'unchanged')
        p.set_processing_busy(True)
        self.assertIn('disabled',p.range_preview_button.state())
        self.assertTrue(all('disabled' in button.state() for button in p.title_preview_buttons.values()))
        p.set_processing_busy(False);self.assertNotIn('disabled',p.range_preview_button.state())
    def test_full_preview_explains_missing_boundary_and_busy_without_enqueuing(self):
        p=self.panel;self.mode(2);p.diamond_enabled.set(True);p.update()
        before=len(self.app.jobs)
        with patch('next_ui.messagebox.showerror') as error,patch.object(self.app,'settings') as settings:
            p.preview();self.assertIn('仅预览此组译文',error.call_args.args[1]);settings.assert_not_called()
        self.assertEqual(len(self.app.jobs),before)
        self.app.busy=True
        with patch('next_ui.messagebox.showinfo') as notice:p.preview();notice.assert_called_once()
        self.app.busy=False;self.assertEqual(len(self.app.jobs),before)

    def test_fixed_ending_requires_preview_and_confirmation_before_filling_boundary(self):
        from ending_reference import stamp,ALGORITHM
        from ending_presets import digest
        p=self.panel;self.mode(2)
        self.assertFalse(p.ending_reference_button.winfo_ismapped())
        p.diamond_enabled.set(True);p.update();self.root.update();p.ending_reference_settings();self.root.update()
        dialog=p.ending_reference_dialog
        source=self.folder/'whole.mp4';source.write_bytes(b'source stamp fixture');self.app.v['video'].set(str(source))
        dialog.root.mkdir(parents=True,exist_ok=True);ref=dialog.root/'reference.mp4';ref.write_bytes(b'reference fixture')
        fingerprint=digest(ref)
        (dialog.root/'reference.json').write_text(json.dumps(dict(schema=1,algorithm=ALGORITHM,file=ref.name,sha256=fingerprint,seconds=20)))
        candidate=dict(source_stamp=stamp(source),reference_id=fingerprint,start=120,score=.99,uncertainty=.125)
        dialog.receive('found',candidate);self.assertEqual(p.v['combined_outro_start'].get(),'0')
        with patch('ending_reference_ui.messagebox.showerror') as error:
            dialog.accept();self.assertTrue(error.called);self.assertEqual(p.v['combined_outro_start'].get(),'0')
        dialog.receive('preview',dict(path='not_opened_in_unit_test.mp4',start=120,source_stamp=stamp(source),reference_id=fingerprint))
        dialog.seconds.set('121')
        with patch('ending_reference_ui.messagebox.showerror') as error:
            dialog.accept();self.assertTrue(error.called);self.assertEqual(p.v['combined_outro_start'].get(),'0')
        dialog.seconds.set('120')
        with patch('ending_reference_ui.messagebox.askyesno',return_value=True):dialog.accept()
        self.assertEqual(p.v['combined_outro_start'].get(),'120.000');dialog.win.destroy()

    def test_cantonese_exposes_required_aligned_srt_and_indonesian_stays_automatic(self):
        self.app.language_name.set('粤语');self.app.language_changed();self.root.update()
        self.assertEqual(self.app.v['language'].get(),'yue');self.assertEqual(self.app.v['alignment'].get(),'timed')
        self.assertTrue(self.app.target_entry.winfo_ismapped())
        self.app.language_name.set('印尼语');self.app.language_changed();self.root.update()
        self.assertEqual(self.app.v['alignment'].get(),'auto');self.assertFalse(self.app.target_entry.winfo_ismapped())

    def test_saved_ui_preferences_restore_and_old_projects_migrate(self):
        from project_vnext import save_project
        p=self.panel;self.mode(1);p.v['intro_enabled'].set(True);p.v['intro_mode'].set('external_music')
        music=self.folder/'music.wav';music.write_bytes(b'test-path-only');p.v['background_audio'].set(str(music));p.appearance_open.set(True);p.update()
        job=p.project();saved=self.folder/'project.json';save_project(saved,job)
        self.mode(0);p.v['background_audio'].set('');p.appearance_open.set(False);p.load(saved);self.root.update()
        self.assertEqual(p.segment_mode.get(),'另加片头 / 片尾');self.assertEqual(p.v['background_audio'].get(),str(music));self.assertTrue(p.appearance_open.get())
        job.pop('ui_state');job['sequence'].update(combined=True,intro_enabled=False,outro_enabled=False,background_audio='');save_project(saved,job);p.load(saved);self.root.update()
        self.assertEqual(p.segment_mode.get(),'整片视频（已有片头片尾）')
    def test_title_dialog_preserves_defaults_and_legacy_disclaimer_is_inactive(self):
        import tkinter as tk
        p=self.panel;self.mode(2);p.diamond_enabled.set(True);p.decoration_settings();self.root.update()
        dialog=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel))
        self.assertFalse(p.v['opening_title_enabled'].get());self.assertFalse(p.v['disclaimer_enabled'].get())
        from tkinter import ttk
        tabs=next(w for w in dialog.winfo_children() if isinstance(w,ttk.Notebook))
        self.assertEqual(len(tabs.tabs()),2)
        self.assertFalse(any('免责声明' in tabs.tab(tab,'text') for tab in tabs.tabs()))
        self.assertEqual(p.v['opening_topic_color'].get(),'#101010')
        self.assertEqual(p.v['opening_topic_font'].get(),'Yuji Boku')
        p.v['opening_title_original'].set('释迦牟尼佛')
        p.v['opening_title_color'].set('#202020')
        self.assertEqual(p.project()['sequence']['opening_title_original'],'释迦牟尼佛')
        p.v['disclaimer_enabled'].set(True);self.root.update()
        self.assertTrue(p.enabled.get());self.assertFalse(p.value()['disclaimer_enabled'])
        p.v['disclaimer_mode'].set('overlay');p.v['disclaimer_seconds'].set('8')
        self.assertEqual(p.project()['sequence']['disclaimer_seconds'],8)
        self.assertEqual(p.project()['sequence']['disclaimer_mode'],'overlay')
        p.v['disclaimer_seconds'].set('')
        with self.assertRaises(ValueError):self.app.settings()
        p.v['disclaimer_seconds'].set('8')
        dialog.destroy()
    def test_chinese_choices_preserve_internal_values_and_reload(self):
        p=self.panel
        self.assertEqual(p.cover_choices['cover_transition'].display.get(),'直接切换')
        p.cover_choices['cover_transition'].display.set('交叉淡化')
        p.cover_choices['cover_transition'].event_generate('<<ComboboxSelected>>')
        self.root.update();self.assertEqual(p.v['cover_transition'].get(),'dissolve')
        p.v['cover_fit'].set('crop');self.root.update()
        self.assertEqual(p.cover_choices['cover_fit'].display.get(),'等比例裁切')
        self.assertEqual(p.project()['sequence']['cover_fit'],'crop')
        self.app.v['speed'].set('1.1')
        from project_vnext import save_project
        path=self.folder/'speed.json';save_project(path,p.project())
        self.app.v['speed'].set('1.0');p.load(path);self.root.update()
        self.assertEqual(self.app.v['speed'].get(),'1.1')
    def test_wheel_scrolls_expanded_page_without_changing_speed(self):
        from tkinter import ttk
        p=self.panel;p.appearance_open.set(True);p.details_open.set(True);self.mode(1)
        p.v['intro_enabled'].set(True);p.v['intro_mode'].set('music_voice');p.update()
        self.app.root.geometry('1000x640');self.root.update()
        canvas=self.app.content_canvas;canvas.yview_moveto(0);self.root.update()
        def descendants(parent):
            for child in parent.winfo_children():yield child;yield from descendants(child)
        speed=next(w for w in descendants(self.root) if isinstance(w,ttk.Combobox) and str(w.cget('textvariable'))==str(self.app.v['speed']))
        speed.event_generate('<MouseWheel>',delta=-120);self.root.update()
        self.assertEqual(self.app.v['speed'].get(),'1.0')
        self.assertGreater(canvas.yview()[0],0)
        canvas.yview_moveto(1);self.root.update()
        self.assertLessEqual(self.app.main_button.winfo_rooty()+self.app.main_button.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
if __name__=='__main__':unittest.main()
