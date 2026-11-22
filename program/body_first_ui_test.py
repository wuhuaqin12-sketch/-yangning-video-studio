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
        self.assertTrue(p.enabled.get());self.assertEqual(self.app.sequence_settings["output_mode"],"portrait")
        self.assertTrue(p.segment_mode_box.winfo_ismapped());self.assertEqual(p.segment_mode_box.master,self.app.material_mode_row)
        self.assertTrue(p.output_mode_box.winfo_ismapped())
        self.assertEqual(p.segments.master,self.app.segment_host)
        for part in (p.controls,p.segments,p.intro,p.outro,p.music,self.app.activity):self.assertFalse(part.winfo_ismapped())
        self.assertFalse(self.app.v['burn'].get())
        self.assertEqual(self.app.v['speed'].get(),'1.0')
        self.assertEqual(self.app.language_name.get(),'按文件名判断')
        self.assertEqual(p.layout_vars['landscape']['subtitle_font_size'].get(),'64')
        self.assertEqual(p.layout_vars['portrait']['subtitle_font_size'].get(),'')
        self.assertEqual(p.layout_vars['landscape']['repair_method'].get(),'glyph')
        self.assertTrue(p.layout_vars['landscape']['repair_full_width'].get())
        self.app.v['video'].set('ordinary.mp4');self.root.update();self.assertTrue(p.enabled.get())
        self.assertLess(self.app.main_button.winfo_rooty()+self.app.main_button.winfo_height(),self.root.winfo_rooty()+self.root.winfo_height())
        self.assertTrue(callable(self.app.advanced));self.assertTrue(callable(self.app.timing_settings));self.assertTrue(callable(self.app.final_export))
    def test_modes_show_only_relevant_fields_and_preserve_disabled_assets(self):
        p=self.panel;self.mode(1)
        self.assertTrue(p.segment_switch.winfo_ismapped());self.assertFalse(p.intro.winfo_ismapped());self.assertFalse(p.outro.winfo_ismapped())
        p.v['intro_enabled'].set(True);p.v['outro_enabled'].set(True);p.v['intro_mode'].set('external_music');p.update();self.root.update()
        self.assertTrue(p.intro.winfo_ismapped());self.assertTrue(p.outro.winfo_ismapped());self.assertTrue(p.music.winfo_ismapped())
        p.v['background_audio'].set('keep-this-music.wav')
        self.mode(0);self.assertFalse(p.segments.winfo_ismapped());self.assertFalse(p.value()['combined']);self.assertFalse(p.value()['intro_enabled']);self.assertFalse(p.value()['outro_enabled']);self.assertEqual(p.value()['background_audio'],'')
        self.assertEqual(p.v['background_audio'].get(),'keep-this-music.wav');self.assertTrue(p.v['intro_enabled'].get())
        self.mode(1);self.assertEqual(p.value()['background_audio'],'keep-this-music.wav')



    def test_inline_font_and_offset_persist_and_intro_advanced_stays_folded(self):
        p=self.panel
        p.style_vars['landscape_subtitle_font_size'].set('200')
        p.style_vars['landscape_subtitle_offset_y'].set('18')
        p.persist_style()
        import app
        saved=json.loads((app.DATA/'style_no_denoise.json').read_text(encoding='utf8'))
        self.assertEqual(saved['landscape_subtitle_font_size'],200)
        self.assertEqual(saved['landscape_subtitle_offset_y'],18)
        self.mode(1);p.v['intro_enabled'].set(True)
        p.intro_choice.set('replace');p.change_intro_sound();self.root.update()
        self.assertEqual(p.v['intro_mode'].get(),'music_voice')
        self.assertTrue(p.intro_voice.winfo_ismapped());self.assertTrue(p.music.winfo_ismapped())
        self.assertFalse(p.intro_more.winfo_ismapped())
        p.toggle_intro_more();self.root.update();self.assertTrue(p.intro_more.winfo_ismapped())
        p.intro_choice.set('original');p.change_intro_sound();self.root.update()
        self.assertFalse(p.intro_voice.winfo_ismapped());self.assertFalse(p.music.winfo_ismapped());self.assertFalse(p.intro_more.winfo_ismapped())

    def test_cantonese_and_indonesian_use_automatic_alignment(self):
        self.app.language_name.set('粤语');self.app.language_changed();self.root.update()
        self.assertEqual(self.app.v['language'].get(),'yue');self.assertEqual(self.app.v['alignment'].get(),'auto')
        self.assertFalse(self.app.target_entry.winfo_ismapped())
        self.assertTrue(self.app.cantonese_mode_row.winfo_ismapped())
        self.assertTrue(self.app.chinese_entry.winfo_ismapped())
        # Old projects retain direct alignment, but the main page now shows
        # that choice and lets users opt in to the Chinese reference.
        self.app.v['cantonese_alignment'].set('direct');self.app.refresh_language_fields();self.root.update()
        self.assertTrue(self.app.cantonese_mode_row.winfo_ismapped())
        self.assertFalse(self.app.chinese_entry.winfo_ismapped())
        self.app.v['cantonese_alignment'].set('chinese');self.app.refresh_language_fields();self.root.update()
        self.assertTrue(self.app.chinese_entry.winfo_ismapped())
        self.app.language_name.set('印尼语');self.app.language_changed();self.root.update()
        self.assertEqual(self.app.v['alignment'].get(),'auto');self.assertFalse(self.app.target_entry.winfo_ismapped())
        self.assertFalse(self.app.cantonese_mode_row.winfo_ismapped())
        self.assertFalse(self.app.chinese_entry.winfo_ismapped())

    def test_saved_ui_preferences_restore_and_old_projects_migrate(self):
        from next_ui import SEGMENT_MODES
        from project_vnext import save_project
        p=self.panel;self.mode(1);p.v['intro_enabled'].set(True);p.v['intro_mode'].set('external_music')
        music=self.folder/'music.wav';music.write_bytes(b'test-path-only');p.v['background_audio'].set(str(music));p.appearance_open.set(True);p.update()
        job=p.project();saved=self.folder/'project.json';save_project(saved,job)
        self.mode(0);p.v['background_audio'].set('');p.appearance_open.set(False);p.load(saved);self.root.update()
        self.assertEqual(p.segment_mode.get(),'片头＋正文＋片尾（分开素材）');self.assertEqual(p.v['background_audio'].get(),str(music));self.assertTrue(p.appearance_open.get())
        job.pop('ui_state');job['sequence'].update(combined=True,intro_enabled=False,outro_enabled=False,background_audio='');save_project(saved,job)
        before=self.app.v['video'].get()
        p.load(saved);self.root.update()
        self.assertEqual(self.app.v['video'].get(),before);self.assertEqual(p.segment_mode.get(),SEGMENT_MODES[2])
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

    def test_roi_mouse_selection_clears_old_approval_and_sets_preview_time(self):
        from roi_picker import RegionDialog
        from roi_picker import stamp
        from PIL import Image
        source=self.folder/'source.mp4';source.write_bytes(b'original')
        image=self.folder/'frame.png';Image.new('RGB',(320,180),'navy').save(image)
        self.app.v['video'].set(str(source))
        with patch.object(self.app,'worker'):
            dialog=RegionDialog(self.panel,'landscape')
        self.root.update()
        dialog.receive('frame',dict(path=str(image),width=320,height=180,total=100,at=60,source_stamp=stamp(source)))
        class Event:pass
        a=Event();a.x=20;a.y=dialog.dh*.6
        b=Event();b.x=dialog.dw*.8;b.y=dialog.dh*.8
        dialog.down(a);dialog.drag(b)
        self.panel.layout_vars['landscape']['repair_approved'].set('old')
        dialog.accept()
        values=self.panel.layout_vars['landscape']
        self.assertEqual(values['repair_approved'].get(),'')
        self.assertEqual(values['repair_preview_start'].get(),'60')
        roi=list(map(int,values['repair_roi'].get().split(',')))
        self.assertEqual((roi[0],roi[2]),(0,320));self.assertGreater(roi[3],20)
        self.assertEqual(source.read_bytes(),b'original');dialog.win.destroy()



    def test_three_modes_expose_full_video_controls_and_layout_defaults(self):
        from next_ui import SEGMENT_MODES
        self.assertEqual(len(SEGMENT_MODES),3)
        def texts(w):
            for c in w.winfo_children():
                try:yield str(c.cget('text'))
                except Exception:pass
                yield from texts(c)
        labels='\n'.join(texts(self.root))
        for retired in ('金刚经视频专用','上下偏移','标题上下位置','新字幕字号（像素，可空）'):
            self.assertNotIn(retired,labels)
        self.assertIn('自动定位片头 / 正文分界',labels);self.assertIn('固定片尾',labels)
        p=self.panel
        for mode in ('landscape','portrait'):
            p.layout_vars[mode]['subtitle_offset_y'].set('200')
            p.layout_vars[mode]['title_y'].set('25')
        self.mode(2);p.v['combined_intro_end'].set('2');p.v['combined_outro_start'].set('100')
        p.v['opening_title_enabled'].set(True);p.v['background_audio'].set('intro_music.wav')
        values=p.value()
        self.assertTrue(values['combined']);self.assertTrue(values['combined_replace_outro']);self.assertTrue(values['opening_title_enabled'])
        self.assertEqual(values['combined_intro_end'],2);self.assertEqual(values['background_audio'],'intro_music.wav')
        self.assertEqual(values['layouts']['landscape']['subtitle_font_size'],'64')
        self.assertEqual(values['layouts']['portrait']['subtitle_font_size'],'')
        self.assertEqual(values['layouts']['landscape']['subtitle_offset_y'],0)
        self.assertEqual(values['layouts']['portrait']['title_y'],'')

    def test_full_video_controls_stay_hidden_in_body_mode_and_title_has_color_picker(self):
        p=self.panel
        self.assertFalse(p.complete.winfo_ismapped())
        def texts(w):
            for c in w.winfo_children():
                try:yield str(c.cget('text'))
                except Exception:pass
                yield from texts(c)
        self.assertIn('选颜色',list(texts(p.controls)))
        self.mode(2);self.assertTrue(p.complete.winfo_ismapped())
        self.mode(0);self.assertFalse(p.complete.winfo_ismapped())

    def test_selected_fixed_outro_is_remembered_as_default(self):
        from ui_assets import load_outro
        p=self.panel;ending=self.folder/'tail.mp4';ending.write_bytes(b'outro fixture')
        with patch('next_ui.filedialog.askopenfilename',return_value=str(ending)):
            p.pick('outro_video')
        self.assertEqual(p.v['outro_video'].get(),str(ending))
        self.assertEqual(load_outro(p.asset_preferences),str(ending.resolve()))
        p.clear_asset('outro_video')
        self.assertEqual(load_outro(p.asset_preferences),'')
    def test_one_click_exports_without_preview_or_confirmation(self):
        self.mode(1);self.panel.v['intro_enabled'].set(True);self.panel.update()
        self.app.language_manual=True
        with patch.object(self.app,'one_click') as export,patch.object(self.panel,'preview') as preview,patch('app.messagebox.showinfo') as notice:
            self.app.one_click_simple();export.assert_called_once();preview.assert_not_called();notice.assert_not_called()
        self.panel.set_processing_busy(True);self.assertIn('disabled',self.panel.range_preview_button.state())
        self.panel.set_processing_busy(False)
    def test_repair_region_can_export_without_confirmation(self):
        values=self.panel.layout_vars['landscape']
        values['repair_roi'].set('0,100,640,40')
        self.assertEqual(values['repair_approved'].get(),'')
        self.assertIn('已选择',self.panel.region_status['landscape'].get())
        self.assertEqual(self.panel.value()['layouts']['landscape']['repair_roi'],'0,100,640,40')

    def test_open_output_uses_chinese_final_folder_instead_of_work_cache(self):
        cache=self.folder/'YangNing_Next_cache';cache.mkdir()
        out=self.folder/'成片';out.mkdir();video=out/'金刚经_日语_横版_16x9.mp4';video.write_bytes(b'video')
        (cache/'report.json').write_text(json.dumps(dict(preview=False,results=[dict(path=str(video))])),encoding='utf8')
        job=dict(sequence={'output_mode':'both'},analysis=str(cache),result=str(cache),output=str(out))
        with patch.object(self.app,'current',return_value=job),patch('app.open_path') as opened:
            self.app.open_result();opened.assert_called_once_with(str(out))
        with patch.object(self.app,'current',return_value=None),patch('app.open_path') as opened:
            self.app.open_result();opened.assert_called_once_with(self.app.v['output'].get())

    def test_style_window_has_only_text_tabs_and_preview_reads_main_background(self):
        import tkinter as tk
        from tkinter import ttk
        from publish_ui import show
        from PIL import Image
        source=self.folder/'body.mp4';source.write_bytes(b'fixture')
        srt=self.folder/'body.srt';srt.write_text('1\n00:00:00,100 --> 00:00:00,800\n字幕\n',encoding='utf8')
        bg=self.folder/'main.png';Image.new('RGB',(32,18),'blue').save(bg)
        self.app.v['video'].set(str(source));self.app.v['source_srt'].set(str(srt));self.app.v['output'].set(str(self.folder/'out'))
        self.panel.mode.set('横版＋竖版');self.panel.change_mode();self.panel.v['background'].set(str(bg))
        self.app.pending_style={'background':'stale-not-used.png','title':'金剛経','video_height':76}
        show(self.app,lambda _:None);self.root.update()
        dialog=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel))
        def widgets(w):
            for child in w.winfo_children():yield child;yield from widgets(child)
        tabs=next(w for w in widgets(dialog) if isinstance(w,ttk.Notebook))
        self.assertEqual([tabs.tab(t,'text') for t in tabs.tabs()],['标题','字幕','重点词颜色'])
        self.panel.style_vars['landscape_subtitle_font_size'].set('120');self.panel.style_vars['portrait_subtitle_font_size'].set('70')
        self.panel.style_vars['landscape_subtitle_offset_y'].set('60');self.panel.style_vars['portrait_subtitle_offset_y'].set('20')
        self.assertFalse(any(isinstance(w,ttk.Spinbox) for w in widgets(dialog)))
        button=next(w for w in widgets(dialog) if isinstance(w,ttk.Button) and w.cget('text')=='预览横版排版')
        with patch.object(self.app,'worker',side_effect=lambda work:work()),patch('style_preview.render',return_value=str(bg)) as render,patch('app.open_path'):
            button.invoke();render.assert_called_once()
            settings,p,ratio=render.call_args.args[:3]
            self.assertEqual(settings['background'],str(bg));self.assertEqual(p['background'],str(bg));self.assertEqual(settings['video'],str(source));self.assertEqual(ratio,'landscape')
            self.assertEqual(settings['landscape_subtitle_offset_y'],60);self.assertEqual(settings['portrait_subtitle_offset_y'],20)
            self.assertEqual(settings['landscape_subtitle_font_size'],120);self.assertEqual(settings['portrait_subtitle_font_size'],70)
            self.app.poll()
        self.assertEqual(self.panel.v['background'].get(),str(bg));dialog.destroy()

if __name__=='__main__':unittest.main()
