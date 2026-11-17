import json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from adaptive_title import plan,times
from project_vnext import defaults,file_digest
from media import run,executable,probe,parse_srt
import intro_boundary as ib
import sequence_vnext as seq

class LayoutTests(unittest.TestCase):
    def test_long_horizontal_pages_preserve_size_and_complete_text(self):
        text='A very long translated lecture title with many words. '*20
        q=plan(text,84,960,900,(0,0,1920,1080))
        self.assertEqual(q['size'],84);self.assertGreater(len(q['pages']),1)
        joined=''.join(''.join(p['lines']) for p in q['pages'])
        self.assertEqual(joined.replace(' ',''),text.replace(' ',''))
        self.assertTrue(all(len(p['lines'])<=5 for p in q['pages']))
        pages=times(q['pages'],2,20)
        self.assertEqual(pages[0][0],2);self.assertEqual(pages[-1][1],20)
        self.assertTrue(all(a[1]==b[0] for a,b in zip(pages,pages[1:])))
    def test_vertical_columns_and_short_page_warning(self):
        text='金剛般若波羅蜜経講義'*30
        q=plan(text,64,300,200,(0,0,640,360),vertical=True)
        self.assertGreater(len(q['pages']),1)
        self.assertEqual(''.join(c['text'] for p in q['pages'] for c in p['columns']),text)
        self.assertTrue(all(c['x']<628 for p in q['pages'] for c in p['columns']))
        self.assertTrue(any(p.get('short_time') for _,_,p in times(q['pages'],0,1)))
    def test_long_landscape_subtitles_stay_below_complete_picture(self):
        from publish import make_ass
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);text='長い字幕をすべて保留して自動的に改行する。'*25
            make_ass(root/'test.ass',[(13,1,21,text)],{'subtitle_font_size':84,'title':''},{'width':1920,'height':1080},23,1920,1080,auto_background=True)
            report=json.loads((root/'layout_report.json').read_text());x,y,w,h=report['video_box']
            self.assertTrue(report['auto_background']);self.assertGreater(report['display_cue_count'],1)
            self.assertAlmostEqual(w/h,1920/1080,delta=.01)
            self.assertGreater(report['subtitle_box'][1],y+h)
            cues=parse_srt(root/'publish_subtitles.srt')
            self.assertEqual(''.join(c[3].replace('\n','') for c in cues),text)
            self.assertTrue(all(len(c[3].splitlines())<=5 for c in cues))
            self.assertEqual((cues[0][1],cues[-1][2]),(1,21))
    def test_local_ocr_disables_runtime_telemetry_before_session_creation(self):
        import opening_caption,types,os
        from unittest.mock import Mock
        runtime=Mock()
        def create(**kw):
            self.assertEqual(os.environ.get('ORT_DISABLE_TELEMETRY'),'1')
            runtime.disable_telemetry_events.assert_called_once()
            return 'local-ocr'
        factory=Mock(side_effect=create)
        opening_caption.engine.cache_clear()
        try:
            with patch.dict(os.environ,{'ORT_DISABLE_TELEMETRY':'0'}),patch.dict('sys.modules',{'onnxruntime':runtime,'rapidocr':types.SimpleNamespace(RapidOCR=factory)}):
                self.assertEqual(opening_caption.engine(),'local-ocr')
        finally:opening_caption.engine.cache_clear()
    def test_mouse_coordinates_full_width_and_reverse_drag(self):
        from roi_picker import rectangle
        self.assertEqual(rectangle(((300,150),(100,120)),(480,270),(1920,1080),True),(0,480,1920,120))
        self.assertEqual(rectangle(((300,150),(100,120)),(480,270),(1920,1080),False),(400,480,800,120))

class BoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);cls.stop=threading.Event();cls.video=cls.root/'input.mp4';cls.audio=cls.root/'voice.wav'
        run([executable('ffmpeg'),'-nostdin','-v','error','-y','-f','lavfi','-i','color=blue:s=320x180:r=10:d=5','-f','lavfi','-i','sine=frequency=440:duration=5','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(cls.video)],cls.stop)
        run([executable('ffmpeg'),'-nostdin','-v','error','-y','-f','lavfi','-i',"aevalsrc=if(lt(t\\,1)\\,0.05*sin(880*PI*t)\\,if(gt(t\\,2)\\,0.05*sin(1320*PI*t)\\,0)):s=16000:d=5",str(cls.audio)],cls.stop)
        run([executable('ffmpeg'),'-nostdin','-v','error','-y','-i',str(cls.video),'-vn',str(cls.root/'input_audio.wav')],cls.stop)
        cls.refs=cls.root/'refs.srt';cls.target=cls.root/'timed.srt';cls.ending=cls.root/'fixed_ending.mp4'
        run([executable('ffmpeg'),'-nostdin','-v','error','-y','-f','lavfi','-i','color=red:s=320x180:r=10:d=1.5','-f','lavfi','-i','sine=frequency=990:duration=1.5','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(cls.ending)],cls.stop)
        cls.music=cls.root/'intro_music.wav'
        run([executable('ffmpeg'),'-nostdin','-v','error','-y','-f','lavfi','-i','sine=frequency=220:duration=2.5','-ar','48000','-ac','2',str(cls.music)],cls.stop)
        cls.cues=[(12,.1,1,'片頭'),(13,2,4,'正文')];cls.targets=[(12,.1,1,'OPENING'),(13,2,4,'BODY')]
        ib.write_srt(cls.refs,cls.cues);ib.write_srt(cls.target,cls.targets)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def detect(self,name='case',aligned=True):
        return ib.detect(self.video,self.audio,self.refs,'en',12,str(self.target) if aligned else '',self.root/name,self.stop)
    def test_aligned_srt_proposes_separate_boundaries_and_previews(self):
        before=[file_digest(p) for p in (self.video,self.audio,self.refs)]
        q=self.detect();self.assertEqual(q['video'],2);self.assertAlmostEqual(q['audio'],1.88)
        self.assertEqual(parse_srt(q['aligned_srt']),self.targets)
        for kind in ('video','audio'):
            preview=ib.preview(q,self.video,self.audio,self.refs,kind,self.root/'previews',self.stop)
            self.assertGreater(float(probe(preview['path'],self.stop)['format']['duration']),1)
        self.assertEqual(before,[file_digest(p) for p in (self.video,self.audio,self.refs)])
    def test_existing_local_alignment_is_used_without_different_model_fallback(self):
        with patch('multilingual.align',return_value=self.targets) as align:
            q=self.detect('model_path',False)
        self.assertEqual(q['method'],'local_reference_alignment');align.assert_called_once()
    def test_unsafe_or_mismatched_narration_is_rejected(self):
        bad=self.root/'bad.srt';ib.write_srt(bad,[(12,.1,1.99,'A'),(13,2,4,'B')])
        with self.assertRaisesRegex(ValueError,'停顿'):ib.detect(self.video,self.audio,self.refs,'en',12,bad,self.root/'bad',self.stop)
        ib.write_srt(bad,[(1,.1,1,'A'),(2,2,4,'B')])
        with self.assertRaisesRegex(ValueError,'编号'):ib.detect(self.video,self.audio,self.refs,'en',12,bad,self.root/'bad',self.stop)
        # Audible tone at the proposed boundary must not be silently cut.
        with self.assertRaisesRegex(ValueError,'明显声音'):ib.detect(self.video,self.root/'input_audio.wav',self.refs,'en',12,self.target,self.root/'loud',self.stop)
    def test_original_audio_boundary_and_changed_alignment(self):
        q=ib.detect(self.video,'',self.refs,'en',12,'',self.root/'original',self.stop)
        self.assertEqual(q['video'],q['audio']);self.assertEqual(q['method'],'original_video_audio')
        Path(q['aligned_srt']).write_text('changed')
        with self.assertRaisesRegex(ValueError,'改变'):ib.verify(q,self.video,'',self.refs)
    def test_confirmed_alignment_reused_with_first_body_word_intact(self):
        q=self.detect('split');p=defaults();p.update(combined=True,outro_video=str(self.ending),background_audio=str(self.music),combined_intro_end=q['video'],combined_audio_split=q['audio'],combined_outro_start=4.5,combined_aligned_srt=q['aligned_srt'],combined_alignment_token=q['token'])
        folder=self.root/'split_result';folder.mkdir(exist_ok=True)
        j,settings=seq.split_combined(dict(video=str(self.video),audio=str(self.audio),source_srt=str(self.refs)),p,folder,self.stop,lambda _:None)
        targets=parse_srt(j['target_srt']);self.assertEqual(targets[0][0],13);self.assertAlmostEqual(targets[0][1],.12)
        self.assertEqual(targets[0][3],'BODY');self.assertEqual(j['alignment'],'timed')
        self.assertEqual(parse_srt(settings['intro_target_srt'])[0][3],'OPENING')
        self.assertAlmostEqual(seq.seconds(folder/'complete_body.mp4',self.stop),2.5,delta=.15)
        self.assertEqual(j['sequence']['outro_video'],str(self.ending))
        self.assertGreater(seq.seconds(self.ending,self.stop),5-4.5)
    def test_complete_export_uses_video_srt_for_visual_cut_and_appends_longer_fixed_tail(self):
        q=self.detect('full_export');p=defaults();p.update(output_mode='landscape',combined=True,outro_video=str(self.ending),background_audio=str(self.music),combined_intro_end=q['video'],combined_audio_split=q['audio'],combined_outro_start=4.5,combined_aligned_srt=q['aligned_srt'],combined_alignment_token=q['token'])
        p['layouts']['landscape']['remove_chinese']=False
        output=self.root/'complete_outputs'
        job=dict(video=str(self.video),audio=str(self.audio),source_srt=str(self.refs),target_srt=str(self.target),alignment='timed',language='en',speed='1.0',trim=False,burn=True,output=str(output),sequence=p,name='complete test')
        folder=Path(seq.process(job,self.stop));report=json.loads((folder/'report.json').read_text())
        result=report['results'][0];path=Path(result['path'])
        self.assertTrue(path.is_file());self.assertTrue(path.with_suffix('.srt').is_file())
        self.assertGreater(result['duration'],5.5)
        self.assertLess(result['duration'],7.0)
        cues=parse_srt(path.with_suffix('.srt'));self.assertEqual([c[3] for c in cues],['OPENING','BODY'])
        frame=self.root/'complete_tail.png';seq.ff(['-ss',str(result['duration']-.5),'-i',path,'-frames:v','1',frame],self.stop)
        from PIL import Image
        with Image.open(frame) as image:self.assertGreater(image.getpixel((100,100))[0],200)
    def test_roi_frame_and_preflight_before_audio_processing(self):
        from roi_picker import frame
        before=file_digest(self.video);info=frame(self.video,2,self.root/'frame',self.stop)
        self.assertEqual((info['width'],info['height']),(320,180));self.assertEqual(before,file_digest(self.video))
        p=defaults();p['output_mode']='landscape'
        with patch('sequence_vnext.aligned',side_effect=AssertionError('audio must not start')):
            with self.assertRaisesRegex(ValueError,'鼠标框选'):seq.process(dict(video=str(self.video),sequence=p,output=str(self.root/'not_started')),self.stop)
        p['layouts']['landscape'].update(repair_roi='0,120,320,30',repair_approved=seq.layout_repair_key(self.video,{**p['layouts']['landscape'],'repair_roi':'0,120,320,30'}))
        seq.preflight_repair(dict(video=str(self.video)),p,self.stop)

