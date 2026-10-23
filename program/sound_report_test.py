import json,tempfile,unittest
from pathlib import Path
import numpy as np
from sound_report import attenuation,output_parts,write_report,load_reference

class SoundReportTests(unittest.TestCase):
    def test_attenuation_excludes_peak_gain_and_ignores_silent_source(self):
        r=1000;x=np.ones(2000,dtype='float32')*.05;x[:500]=0
        y=x*.5
        self.assertEqual(attenuation(x,y,r,.5),[])
        y[700:1200]*=.1
        rows=attenuation(x,y,r,.5)
        self.assertEqual(len(rows),1);self.assertAlmostEqual(rows[0]['start'],.7);self.assertAlmostEqual(rows[0]['end'],1.2)
        self.assertEqual(rows[0]['classification'],'signal_attenuation_only')
    def test_cut_and_speed_keep_only_surviving_mute_parts(self):
        parts=output_parts(1,5,[dict(kind='cut',start=2,end=3)],2)
        self.assertEqual(parts,[dict(start=.5,end=1,seconds=.5),dict(start=1,end=2,seconds=1)])
        self.assertEqual(output_parts(2,3,[dict(kind='cut',start=2,end=3)],1.1),[])
    def test_insertions_are_excluded_from_original_audio_spans(self):
        events=[dict(kind='add',start=2,end=2,seconds=.6)]
        parts=output_parts(1,3,events,2)
        self.assertEqual(parts[0],dict(start=.5,end=1,seconds=.5))
        self.assertEqual(parts[1],dict(start=1.3,end=1.8,seconds=.5))
    def test_reports_distinguish_mutes_cuts_scope_and_subtitle_overlap(self):
        with tempfile.TemporaryDirectory() as d:
            events=[dict(kind='cut',start=1,end=2,reason='自动空白剪短'),dict(kind='add',start=4,end=4,seconds=.4)]
            meta=dict(enabled=True,denoise_enabled=True,mode='v11_deep',attenuated_intervals=[dict(start=2.5,end=3,mean_drop_db=12)])
            r=write_report(d,meta,6,events=events,mutes=[dict(start=2.5,end=3,fade_start=2.495,fade_end=3.005)],speed=2,cues=[(1,2.4,3.1,'対応字幕')],subtitle_reference='a.srt')
            m=next(e for e in r['entries'] if e['kind']=='mute')
            self.assertEqual(m['subtitle_text'],'対応字幕');self.assertEqual(m['output_intervals'][0]['start'],.75)
            cut=next(e for e in r['entries'] if e['kind']=='cut');self.assertEqual(cut['output_intervals'],[])
            add=next(e for e in r['entries'] if e['kind']=='inserted_silence');self.assertEqual(add['output_intervals'],[dict(start=1.5,end=1.7,seconds=.2)])
            self.assertFalse(r['all_noise_removed_certified']);self.assertFalse(r['hearing_review_complete'])
            self.assertTrue((Path(d)/'声音处理明细.csv').read_bytes().startswith(b'\xef\xbb\xbf'))
            write_report(d,{},6)
            r=json.loads((Path(d)/'声音处理明细.json').read_text());self.assertEqual(r['entries'],[])
    def test_reference_range_checks_are_not_speech_verification(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'对应字幕.srt';p.write_text('1\n00:00:00,200 --> 00:00:01,800\n対応字幕\n',encoding='utf8')
            ref=load_reference(p,2)
            self.assertFalse(ref['reference_timing_verified']);self.assertEqual(ref['reference_cues'][0][3],'対応字幕')
            with self.assertRaisesRegex(ValueError,'超过当前音频时长'):load_reference(p,1)
    def test_gap_mute_reports_neighboring_subtitles(self):
        with tempfile.TemporaryDirectory() as d:
            r=write_report(d,{},5,mutes=[dict(start=2,end=2.5)],cues=[(1,0,1,'前の文'),(2,3,4,'散乱しているのか')])
            m=r['entries'][0]
            self.assertEqual(m['subtitle_text'],'');self.assertEqual(m['next_subtitle'],'散乱しているのか');self.assertEqual(m['previous_subtitle'],'前の文')
            self.assertAlmostEqual(m['output_seconds'],.5)
    def test_same_point_insertions_report_distinct_output_intervals(self):
        with tempfile.TemporaryDirectory() as d:
            events=[dict(kind='add',start=1,end=1,seconds=.3),dict(kind='add',start=1,end=1,seconds=.2)]
            r=write_report(d,{},3,events=events)
            a,b=[e['output_intervals'][0] for e in r['entries']]
            self.assertAlmostEqual(a['start'],1);self.assertAlmostEqual(a['end'],1.3)
            self.assertAlmostEqual(b['start'],1.3);self.assertAlmostEqual(b['end'],1.5)

if __name__=='__main__':unittest.main()
