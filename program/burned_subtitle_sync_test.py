"""Regression of restored v0.14.3 sentence-start picture mapping."""
import unittest
from engine import visual_timeline

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
        self.assertEqual(anchors,[0.,35.4,35.68,42.])
