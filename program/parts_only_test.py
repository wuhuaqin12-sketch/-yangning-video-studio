"""Exercise independent sources, local timelines and direct full exports."""
import json,tempfile,threading,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
import numpy as np
from project_vnext import defaults,file_digest
from media import executable,parse_srt
import sequence_vnext as seq

class PartsOnlyTests(unittest.TestCase):
    def test_retired_queue_stops_before_reading_or_changing_media(self):
        with patch('sequence_vnext.probe',side_effect=AssertionError('must not read media')):
            with self.assertRaisesRegex(ValueError,'已撤下'):
                seq.process({'sequence':{'combined':True}},threading.Event())
        self.assertFalse(hasattr(seq,'split_combined'))
    def test_independent_intro_body_outro_direct_dual_export_has_correct_audio_and_cues(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cancel=threading.Event();clips=[]
            for name,seconds,tone,color in [('intro',.8,440,'blue'),('body',.8,660,'green'),('ending',1.2,990,'red')]:
                path=root/(name+'.mp4');seq.ff(['-f','lavfi','-i',f'color={color}:s=320x180:r=30:d={seconds}','-f','lavfi','-i',f'sine=frequency={tone}:duration={seconds}','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',path],cancel);clips.append(path)
            voice=root/'intro_voice.wav';seq.ff(['-f','lavfi','-i','sine=frequency=880:duration=0.4',voice],cancel)
            intro_srt=root/'intro.srt';intro_target=root/'intro_timed.srt';body_srt=root/'body.srt'
            seq.write_srt(intro_srt,[(1,.1,.4,'片頭')]);seq.write_srt(intro_target,[(1,0,.3,'片頭')]);seq.write_srt(body_srt,[(13,.1,.7,'正文')])
            q=defaults();q.update(output_mode='both',intro_enabled=True,intro_video=str(clips[0]),intro_mode='music_voice',intro_audio=str(voice),intro_srt=str(intro_srt),intro_target_srt=str(intro_target),intro_clean_audio=True,intro_music_gain=.4,outro_enabled=True,outro_video=str(clips[2]))
            q['layouts']['landscape']['remove_chinese']=False
            job=dict(video=str(clips[1]),audio=str(clips[1]),source_srt=str(body_srt),target_srt=str(body_srt),alignment='timed',language='ja',speed=1,trim=False,burn=True,output=str(root/'out'),sequence=q,name='三段测试')
            before=[file_digest(p) for p in [*clips,voice,intro_srt,intro_target,body_srt]]
            # Direct export needs neither a prior preview nor a confirmation token.
            folder=Path(seq.process(job,cancel));report=json.loads((folder/'report.json').read_text())
            self.assertFalse(report['preview']);self.assertEqual(len(report['results']),2)
            for result,ratio in zip(report['results'],('横版_16x9','竖版_9x16')):
                path=Path(result['path']);self.assertIn(ratio,path.stem)
                self.assertAlmostEqual(seq.seconds(path,cancel),2.8,delta=.16)
                self.assertGreater(seq.seconds(path,cancel),2)
                cues=parse_srt(path.with_suffix('.srt'))
                self.assertEqual([c[3] for c in cues],['片頭','正文'])
                self.assertAlmostEqual(cues[0][1],.1,delta=.05)
                self.assertAlmostEqual(cues[1][1],.9,delta=.05)
                self.assertLess(cues[-1][2],seq.seconds(path,cancel)-1)
                for at,expected in ((.2,880),(1,660),(2.2,990)):
                    raw=subprocess.check_output([executable('ffmpeg'),'-v','error','-ss',str(at),'-i',str(path),'-t','0.12','-vn','-ar','8000','-ac','1','-f','f32le','-'])
                    samples=np.frombuffer(raw,np.float32);peak=np.argmax(abs(np.fft.rfft(samples)))*8000/len(samples)
                    self.assertAlmostEqual(peak,expected,delta=15)
            self.assertEqual(before,[file_digest(p) for p in [*clips,voice,intro_srt,intro_target,body_srt]])
    def test_long_landscape_subtitles_preserve_all_text_outside_video(self):
        from publish import make_ass
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);text='長い字幕を省略せず読みやすく改行します。'*30
            make_ass(root/'test.ass',[(1,0,20,text)],{'subtitle_font_size':84,'title':''},{'width':1920,'height':1080},20,1920,1080,auto_background=True)
            report=json.loads((root/'layout_report.json').read_text());x,y,w,h=report['video_box']
            self.assertTrue(report['auto_background']);self.assertGreater(report['subtitle_box'][1],y+h)
            self.assertEqual(report['subtitle_actual_px'],[84]);self.assertGreater(report['display_cue_count'],1)
            cues=parse_srt(root/'publish_subtitles.srt');self.assertEqual(''.join(c[3].replace('\n','') for c in cues),text)
            self.assertEqual((cues[0][1],cues[-1][2]),(0,20));self.assertTrue(all(len(c[3].splitlines())<=5 for c in cues))
