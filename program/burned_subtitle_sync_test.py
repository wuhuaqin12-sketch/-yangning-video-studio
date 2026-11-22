"""Regression of restored v0.14.3 sentence-start picture mapping."""
import unittest
import tempfile,threading,json
from pathlib import Path
import numpy as np
from PIL import Image
from media import executable,run,parse_srt
from engine import prepare,render,render_preview
from engine import visual_timeline,trimmed_visual_timeline,picture_motion_warnings

SOURCE_42_57=[(202.73,205.53),(206.23,209.30),(209.43,212.90),
              (212.90,217.23),(218.33,222.30),(222.37,223.63),
              (223.87,227.63),(227.63,231.13),(231.63,234.07),
              (234.07,237.80),(237.83,239.87),(240.03,243.27),
              (244.03,246.00),(246.67,249.30),(249.30,253.30),
              (253.63,255.60)]

class BurnedSubtitleSyncTests(unittest.TestCase):
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
    def test_bilingual_caption_ends_align_when_both_have_real_gaps(self):
        source=[(1,0.,2.,'中一'),(2,2.5,4.5,'中二')]
        target=[(1,0.,3.,'外一'),(2,3.8,6.8,'外二')]
        mapped,_=visual_timeline(source,target,5.,7.5)
        self.assertAlmostEqual(float(mapped(3.)),2.,places=6)
        self.assertAlmostEqual(float(mapped(3.8)),2.5,places=6)
        self.assertAlmostEqual(float(mapped(6.8)),4.5,places=6)

    def test_adjacent_voice_cues_never_add_microsecond_picture_jump(self):
        source=[(1,0.,1.,'中一'),(2,1.5,2.5,'中二')]
        target=[(1,0.,1.,'外一'),(2,1.,2.,'外二')]
        mapped,anchors=visual_timeline(source,target,3.,2.5)
        self.assertEqual(anchors,[0.,1.,2.,2.5])
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

    def test_trial_shortens_cue_thirteen_without_touching_voice_or_subtitles(self):
        original=[(12,26.333,29.333,'前句'),(13,30.333,33.666,'本句'),
                  (14,34.333,37.666,'后句')]
        voice=[(12,28.920,32.200,'前句'),(13,35.400,35.680,'本句'),
               (14,35.680,37.920,'后句')]
        picture,_=trimmed_visual_timeline(original,voice,40.,42.)
        self.assertAlmostEqual(picture(35.4),33.386,places=3)
        self.assertAlmostEqual(picture(35.67),33.656,places=3)
        self.assertAlmostEqual(picture.derivative()(35.5),1.,places=3)
        self.assertTrue(any(row['cue']==14 and abs(row['skipped_source_seconds']-.667)<.002
                            for row in picture.cut_events))
        self.assertEqual(voice[1][1:3],(35.4,35.68))

    def test_trial_keeps_forward_only_picture_with_reported_hard_cuts(self):
        original=[(1,0.,1.,'一'),(2,1.2,4.2,'二'),(3,4.5,6.,'三')]
        voice=[(1,0.,1.,'一'),(2,1.5,1.8,'二'),(3,1.8,3.,'三')]
        picture,anchors=trimmed_visual_timeline(original,voice,6.5,3.5)
        self.assertEqual(anchors[0],0.)
        self.assertAlmostEqual(picture(1.65),4.05)
        self.assertAlmostEqual(picture.derivative()(1.65),1.)
        self.assertGreater(float(picture(1.8))-float(picture(1.8-1e-6)),.2)
        self.assertTrue(any('cut_source_seconds' in w for w in
                            picture_motion_warnings(picture,original,voice,6.5,3.5)))

    def test_trial_preview_and_export_share_source_frame_and_keep_voice_srt(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);cancel=threading.Event();ff=executable('ffmpeg')
            run([ff,'-v','error','-y','-f','lavfi','-i',
                 'testsrc2=size=96x64:rate=10:duration=6.5',
                 '-c:v','libx264',str(p/'original.mp4')],cancel)
            run([ff,'-v','error','-y','-f','lavfi','-i',
                 'sine=frequency=440:sample_rate=16000:duration=3.5',
                 str(p/'voice.wav')],cancel)
            (p/'source.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\n一\n\n'
                '2\n00:00:01,200 --> 00:00:04,200\n二\n\n'
                '3\n00:00:04,500 --> 00:00:06,000\n三\n',encoding='utf8')
            (p/'voice.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\none\n\n'
                '2\n00:00:01,500 --> 00:00:01,800\ntwo\n\n'
                '3\n00:00:01,800 --> 00:00:03,000\nthree\n',encoding='utf8')
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
            self.assertEqual(report['picture_fit'],'trim')
            self.assertTrue(report['visual_review_required'])
            self.assertTrue(any(w.get('cut_source_seconds') for w in report['picture_motion_warnings']))

    def test_trial_uses_separate_video_and_preview_cache(self):
        from project_vnext import processing_key,preview_key
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'input';p.write_text('sample')
            shared=dict(video=str(p),audio=str(p),source_srt=str(p),target_srt=str(p))
            smooth={**shared,'picture_fit':'smooth'}
            trim={**shared,'picture_fit':'trim'}
            self.assertNotEqual(processing_key(smooth),processing_key(trim))
            self.assertNotEqual(preview_key(smooth),preview_key(trim))
