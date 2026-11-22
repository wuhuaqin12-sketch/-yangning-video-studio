"""Regression of original-picture mapping for sutra cues 42–57."""
import unittest
from engine import visual_timeline

SOURCE_42_57=[(202.73,205.53),(206.23,209.30),(209.43,212.90),
              (212.90,217.23),(218.33,222.30),(222.37,223.63),
              (223.87,227.63),(227.63,231.13),(231.63,234.07),
              (234.07,237.80),(237.83,239.87),(240.03,243.27),
              (244.03,246.00),(246.67,249.30),(249.30,253.30),
              (253.63,255.60)]

class BurnedSubtitleSyncTests(unittest.TestCase):
    def test_all_sixteen_original_caption_starts_and_ends_are_preserved(self):
        source=[];target=[];clock=10.
        for index,(a,b) in enumerate(SOURCE_42_57):
            ident=42+index
            if index:clock+=(a-SOURCE_42_57[index-1][1])*.8
            start=clock;clock+=(b-a)*(1.3 if index%2 else .75)
            source.append((ident,a,b,str(ident)));target.append((ident,start,clock,str(ident)))
        mapped,_=visual_timeline(source,target,260.,90.)
        for original,spoken in zip(source,target):
            self.assertAlmostEqual(float(mapped(spoken[1])),original[1],places=6)
            self.assertAlmostEqual(float(mapped(spoken[2])),original[2],places=6)
    def test_touching_voice_cues_with_a_source_pause_keep_the_next_start(self):
        source=[(1,0.,1.,'first'),(2,1.5,2.,'second')]
        voice=[(1,0.,1.,'first'),(2,1.,2.,'second')]
        mapped,_=visual_timeline(source,voice,2.5,2.5)
        self.assertAlmostEqual(float(mapped(.999)),1.)
        self.assertAlmostEqual(float(mapped(1.)),1.5)
        self.assertAlmostEqual(float(mapped(2.)),2.)
    def test_no_output_tail_preserves_last_spoken_picture(self):
        source=[(1,0.,1.,'first')];voice=[(1,0.,1.,'first')]
        mapped,_=visual_timeline(source,voice,2.,1.)
        self.assertAlmostEqual(float(mapped(1.)),1.)
    def test_first_cue_start_with_a_leading_pause_is_anchored(self):
        source=[(1,2.,3.,'first')];voice=[(1,1.,2.,'first')]
        mapped,_=visual_timeline(source,voice,4.,3.)
        self.assertAlmostEqual(float(mapped(1.)),2.)
    def test_inconsistent_cue_boundaries_fail_instead_of_shifting_picture(self):
        source=[(42,1.,2.,'一'),(43,2.,3.,'二')]
        spoken=[(42,1.,2.2,'一'),(43,2.,3.,'二')]
        with self.assertRaisesRegex(ValueError,'重叠'):
            visual_timeline(source,spoken,4.,4.)
