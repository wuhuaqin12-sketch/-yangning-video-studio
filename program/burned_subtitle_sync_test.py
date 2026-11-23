"""Regression of restored v0.14.3 sentence-start picture mapping."""
import unittest
import tempfile,threading,json
from pathlib import Path
import numpy as np
from PIL import Image
from media import executable,run,parse_srt
from engine import prepare,render,render_preview
from engine import visual_timeline,selected_visual_timeline,picture_motion_warnings,subtitle_gap_sound
from audio_edit import extend_short_sentences,mapped_cue_start,mapped,apply
from picture_cuts import picture_clock,quiet_picture_cuts

SOURCE_42_57=[(202.73,205.53),(206.23,209.30),(209.43,212.90),
              (212.90,217.23),(218.33,222.30),(222.37,223.63),
              (223.87,227.63),(227.63,231.13),(231.63,234.07),
              (234.07,237.80),(237.83,239.87),(240.03,243.27),
              (244.03,246.00),(246.67,249.30),(249.30,253.30),
              (253.63,255.60)]

class BurnedSubtitleSyncTests(unittest.TestCase):
    def test_short_voice_fills_sentence_end_without_touching_speech_or_frames(self):
        source=[(1,0.,3.8,'一'),(2,3.8,6.8,'二')]
        voice=[(1,0.,1.5,'one'),(2,1.5,5.8,'two')]
        with tempfile.TemporaryDirectory() as directory:
            raw=Path(directory)/'voice.f32';edited=Path(directory)/'edited.f32'
            signal=np.ones(58000,dtype=np.float32)*.2;signal.tofile(raw)
            events,additions=extend_short_sentences(source,voice,[],6.8,5.8,1.)
            self.assertAlmostEqual(sum(e['seconds'] for e in additions),.8)
            total=apply(raw,edited,10000,1,events,threading.Event())
            self.assertAlmostEqual(total,6.6,places=3)
            pcm=np.fromfile(edited,np.float32)
            self.assertTrue(np.all(pcm[:14950]==signal[:14950]))
            self.assertTrue(np.all(pcm[15000:23000]==0.))
            self.assertTrue(np.all(pcm[23050:]==signal[15050:]))
            self.assertAlmostEqual(mapped(voice[0][2],events),1.5)
            second=mapped_cue_start(voice[1][1],events)
            self.assertAlmostEqual(second,2.3)
            adjusted=[(1,0.,1.5,'one'),(2,second,mapped(voice[1][2],events),'two')]
            picture,_=selected_visual_timeline(source,adjusted,6.8,total,{'picture_fit':'adaptive'})
            self.assertAlmostEqual(float(picture(second)),3.8)
            self.assertGreater(max(float(picture.derivative()(t)) for t in np.linspace(0,second,10)),1.)
    def test_only_subtitle_gap_can_be_cut_and_preview_has_same_jump(self):
        source=[(1,0.,1.,'中一'),(2,2.,3.,'中二')]
        cuts=[dict(cue=1,start=1.2,end=1.7)]
        virtual,duration,restore,_=picture_clock(source,cuts,3.5)
        self.assertAlmostEqual(virtual[1][1],1.5)
        target=[(1,0.,1.,'one'),(2,1.5,2.5,'two')]
        picture,_=selected_visual_timeline(source,target,3.5,3.,{'picture_fit':'adaptive','_picture_cuts':cuts})
        self.assertAlmostEqual(float(picture(1.5)),2.)
        self.assertEqual(len(picture.cut_events),1)
        with self.assertRaisesRegex(ValueError,'不能跨句或剪切句首句尾'):
            picture_clock(source,[dict(cue=1,start=.8,end=1.2)],3.5)
    def test_quiet_original_audio_and_still_gap_permit_small_picture_cut(self):
        with tempfile.TemporaryDirectory() as directory:
            movie=Path(directory)/'original.mp4'
            run([executable('ffmpeg'),'-v','error','-y','-f','lavfi','-i','color=c=gray:s=160x90:r=15:d=3',
                 '-f','lavfi','-i','anullsrc=r=44100:cl=mono','-t','3',
                 '-c:v','libx264','-c:a','aac',str(movie)],threading.Event())
            source=[(1,0.,.6,'one'),(2,2.,2.5,'two')]
            cuts=quiet_picture_cuts(movie,source,3.,True,threading.Event(),{1:1.})
            self.assertEqual(len(cuts),1)
            self.assertEqual(cuts[0]['cue'],1)
            self.assertGreaterEqual(cuts[0]['start'],.6)
            self.assertLessEqual(cuts[0]['end'],2.)
            self.assertEqual(quiet_picture_cuts(movie,source,3.,False,threading.Event(),{1:1.}),[])
            inside=quiet_picture_cuts(movie,[(1,0.,1.7,'one'),(2,2.5,2.8,'two')],3.,False,
                                      threading.Event(),{1:1.})
            self.assertTrue(any(.3<=c['start']<c['end']<1.7 for c in inside))
    def test_sentence_pause_waits_until_existing_audio_cut_finishes(self):
        src=[(1,0.,1.,'一'),(2,2.,3.,'二')]
        dst=[(1,0.,.8,'one'),(2,1.5,2.5,'two')]
        existing=[dict(enabled=True,kind='cut',start=.75,end=1.,seconds=.25,
                       safe_start=.7,safe_end=1.05,reason='静音')]
        events,adds=extend_short_sentences(src,dst,existing,3.5,3.,1.)
        self.assertEqual(len(adds),1)
        self.assertAlmostEqual(adds[0]['start'],1.)
        self.assertGreater(mapped_cue_start(dst[1][1],events),1.25)
    def test_sutra_cues_42_to_57_preserve_original_picture_starts(self):
        source=[(41,200.,202.,'41')];target=[(41,8.,9.,'41')];clock=10.
        for index,(a,b) in enumerate(SOURCE_42_57):
            ident=42+index
            if index:clock+=(a-SOURCE_42_57[index-1][1])*.8
            start=clock;clock+=(b-a)*(1.3 if index%2 else .75)
            source.append((ident,a,b,str(ident)));target.append((ident,start,clock,str(ident)))
        mapped,_=visual_timeline(source,target,260.,90.)
        for original,spoken in zip(source[1:],target[1:]):
            self.assertAlmostEqual(float(mapped(spoken[1])),original[1],places=6)
    def test_legacy_mapping_uses_sentence_starts_even_with_generous_gaps(self):
        source=[(1,0.,2.,'一'),(2,2.5,4.5,'二')]
        voice=[(1,0.,3.,'one'),(2,3.8,6.8,'two')]
        mapping,anchors=visual_timeline(source,voice,5.,7.5)
        self.assertEqual(anchors,[0.,3.8,7.5])
        self.assertAlmostEqual(float(mapping(3.8)),2.5)
        self.assertNotAlmostEqual(float(mapping(3.)),2.)

    def test_adjacent_voice_cues_never_add_microsecond_picture_jump(self):
        source=[(1,0.,1.,'中一'),(2,1.5,2.5,'中二')]
        target=[(1,0.,1.,'外一'),(2,1.,2.,'外二')]
        mapped,anchors=visual_timeline(source,target,3.,2.5)
        self.assertEqual(anchors,[0.,1.,2.5])
        self.assertAlmostEqual(float(mapped(1.)),1.5,places=6)

    def test_touching_voice_cues_use_legacy_sentence_starts(self):
        source=[(1,0.,1.,'first'),(2,1.5,2.,'second')]
        voice=[(1,0.,1.,'first'),(2,1.,2.,'second')]
        mapped,_=visual_timeline(source,voice,2.5,2.5)
        self.assertAlmostEqual(float(mapped(1.)),1.5)
    def test_legacy_mapping_uses_video_tail_anchor(self):
        source=[(1,0.,1.,'first')];voice=[(1,0.,1.,'first')]
        mapped,_=visual_timeline(source,voice,2.,1.)
        self.assertAlmostEqual(float(mapped(1.)),2.)
    def test_non_increasing_sentence_starts_fail(self):
        source=[(42,1.,2.,'一'),(43,2.,3.,'二'),(44,3.,4.,'三')]
        spoken=[(42,0.,1.,'一'),(43,1.,2.,'二'),(44,1.,3.,'三')]
        with self.assertRaisesRegex(ValueError,'递增时间轴'):
            visual_timeline(source,spoken,4.,4.)
    def test_short_cue_does_not_add_new_end_anchor(self):
        source=[(12,26.333,29.333,'前句'),(13,30.333,33.666,'本句'),(14,34.333,37.666,'后句')]
        target=[(12,28.920,32.200,'前句'),(13,35.400,35.680,'本句'),(14,35.680,37.920,'后句')]
        _,anchors=visual_timeline(source,target,40.,42.)
        self.assertIn(35.4,anchors)
        self.assertIn(35.68,anchors)
        self.assertNotIn(35.680 - .001,anchors)
        self.assertEqual(anchors[-1],42.)
        mapping,_=visual_timeline(source,target,40.,42.)
        self.assertTrue(any(row['cue']==13 and row['max_picture_speed']>4
                            for row in picture_motion_warnings(mapping,source,target,40.,42.)))

    def test_long_source_gap_cannot_be_compressed_into_short_voice_gap(self):
        original=[(1,0.,2.,'一'),(2,5.,7.,'二')]
        voice=[(1,0.,2.,'一'),(2,2.3,4.3,'二')]
        mapping,anchors=visual_timeline(original,voice,8.,5.)
        self.assertNotIn(2.,anchors)
        self.assertAlmostEqual(float(mapping(2.3)),5.)
        self.assertTrue(any(row['cue']==1 for row in picture_motion_warnings(mapping,original,voice,8.,5.)))

    def test_disproportionate_sentence_keeps_stable_start_mapping(self):
        original=[(1,0.,3.33,'一'),(2,4.,6.,'二')]
        voice=[(1,0.,.28,'一'),(2,.8,2.8,'二')]
        _,anchors=visual_timeline(original,voice,7.,4.)
        self.assertNotIn(.28,anchors)
        self.assertIn(.8,anchors)

    def test_no_gap_does_not_divide_by_zero_or_insert_end(self):
        original=[(1,0.,1.,'一'),(2,1.5,2.5,'二')]
        voice=[(1,0.,0.,'一'),(2,1.,2.,'二')]
        _,anchors=visual_timeline(original,voice,3.,3.)
        self.assertNotIn(0.,anchors[1:])
        self.assertNotIn(0.0001,anchors)

    def test_legacy_mode_ignores_saved_picture_cut_setting(self):
        from workflow import normalize
        source=[(1,0.,1.,'一'),(2,1.2,4.2,'二'),(3,4.5,6.,'三')]
        voice=[(1,0.,1.,'one'),(2,1.5,1.8,'two'),(3,1.8,3.,'three')]
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'input';p.write_text('sample')
            job=normalize(dict(picture_fit='trim',video=str(p),audio=str(p),
                               source_srt=str(p),target_srt=str(p),output=directory,
                               language='en',alignment='timed'))
        self.assertEqual(job['picture_fit'],'smooth')
        picture,anchors=selected_visual_timeline(source,voice,6.5,3.5,job)
        self.assertEqual(anchors,[0.,1.5,1.8,3.5])
        self.assertAlmostEqual(float(picture(1.5)),1.2)
        self.assertAlmostEqual(float(picture(1.8)),4.5)
        self.assertFalse(hasattr(picture,'cut_events'))

    def test_legacy_preview_and_export_use_same_source_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);cancel=threading.Event();ff=executable('ffmpeg')
            run([ff,'-v','error','-y','-f','lavfi','-i',
                 'testsrc2=size=96x64:rate=10:duration=3.5',
                 '-c:v','libx264',str(p/'original.mp4')],cancel)
            run([ff,'-v','error','-y','-f','lavfi','-i',
                 'sine=frequency=440:sample_rate=16000:duration=3.5',
                 str(p/'voice.wav')],cancel)
            (p/'source.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\n一\n\n'
                 '2\n00:00:01,200 --> 00:00:02,200\n二\n\n'
                '3\n00:00:02,500 --> 00:00:03,200\n三\n',encoding='utf8')
            (p/'voice.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\none\n\n'
                 '2\n00:00:01,500 --> 00:00:02,300\ntwo\n\n'
                '3\n00:00:02,400 --> 00:00:03,000\nthree\n',encoding='utf8')
            job=dict(video=str(p/'original.mp4'),audio=str(p/'voice.wav'),
                     source_srt=str(p/'source.srt'),target_srt=str(p/'voice.srt'),
                     output=str(p/'out'),language='en',alignment='timed',
                     trim=False,burn=False,picture_fit='trim')
            folder=Path(prepare(job,cancel))
            with Image.open(render_preview(folder,1.65,cancel)) as im:
                preview=np.asarray(im.convert('RGB')).astype('int16')
            render(folder,cancel)
            run([ff,'-v','error','-y','-ss','1.65','-i',str(folder/'video.mp4'),
                 '-frames:v','1',str(p/'export_frame.png')],cancel)
            with Image.open(p/'export_frame.png') as im:
                output=np.asarray(im.convert('RGB')).astype('int16')
            self.assertLess(float(np.mean(np.abs(output-preview))),30.)
            self.assertEqual([c[3] for c in parse_srt(folder/'subtitles.srt')],
                             ['one','two','three'])
            report=json.loads((folder/'report.json').read_text(encoding='utf8'))
            self.assertEqual(report['picture_fit'],'smooth')
            self.assertFalse(any(w.get('cut_source_seconds') for w in report['picture_motion_warnings']))

    def test_audio_activity_in_subtitle_gap_is_reported_without_retiming(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'voice.f32'
            voice=np.zeros(30000,dtype=np.float32)
            voice[15000:23000]=.2
            voice.tofile(path)
            cues=[(1,0.,1.,'one'),(2,2.5,3.,'two')]
            warnings=subtitle_gap_sound(path,10000,1,cues,3.)
            self.assertEqual(len(warnings),1)
            self.assertEqual(warnings[0]['output_start'],1.)
            self.assertEqual(warnings[0]['output_end'],2.5)
            self.assertEqual(cues[1][1],2.5)
