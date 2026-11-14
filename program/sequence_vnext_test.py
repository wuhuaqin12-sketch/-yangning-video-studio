import json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import project_vnext as p
import sequence_vnext as s
from media import probe,parse_srt

class ProjectTests(unittest.TestCase):
    def test_defaults_and_independent_layouts(self):
        a=p.defaults();b=p.defaults();a['layouts']['portrait']['subtitle_offset_y']=50
        self.assertEqual(b['layouts']['portrait']['subtitle_offset_y'],0)
        self.assertTrue(b['layouts']['landscape']['remove_chinese']);self.assertFalse(b['layouts']['portrait']['remove_chinese'])
        self.assertEqual(p.normalize({'cover_seconds':'3'})['cover_seconds'],3)
    def test_save_load_reports_missing_and_keeps_fields(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'project.json';j=dict(video=str(Path(d)/'missing.mp4'),sequence=p.defaults(),burn=False)
            j['sequence'].update(intro_enabled=True,intro_video=str(Path(d)/'opening.mp4'),outro_enabled=True,outro_video=str(Path(d)/'ending.mp4'))
            p.save_project(f,j);loaded,missing=p.load_project(f)
            self.assertEqual(loaded['sequence'],j['sequence']);self.assertEqual(len(missing),3);self.assertFalse(loaded['burn'])
    def test_visual_edits_reuse_key_but_interior_audio_change_does_not(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'a';f.write_bytes(b'a'*200000)
            j=dict(video=str(f),audio=str(f),source_srt=str(f),target_srt=str(f),speed=1.0)
            key=p.processing_key(j)
            self.assertEqual(key,p.processing_key({**j,'publish_settings':{'title':'changed'},'burn':True,'sequence':{'cover':'new'}}))
            with f.open('r+b') as stream:stream.seek(100000);stream.write(b'z')
            self.assertNotEqual(key,p.processing_key(j))
    def test_collision_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            first=p.unique_output(d,'sutra','ja','portrait');first.write_bytes(b'keep')
            second=p.unique_output(d,'sutra','ja','portrait')
            self.assertNotEqual(first,second);self.assertEqual(first.read_bytes(),b'keep')
    def test_portable_project_resolves_paths_from_its_own_folder(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'assets').mkdir();(root/'assets/body.mp4').write_bytes(b'media')
            p.save_project(root/'project.json',dict(video='assets/body.mp4',output='output',sequence=p.defaults()))
            job,missing=p.load_project(root/'project.json')
            self.assertFalse(missing);self.assertEqual(Path(job['video']).resolve(),(root/'assets/body.mp4').resolve())
            self.assertEqual(Path(job['output']).resolve(),(root/'output').resolve())
            (root/'assets/music.wav').write_bytes(b'music')
            job['sequence']['background_audio']='assets/music.wav'
            p.save_project(root/'music.json',job)
            loaded,missing=p.load_project(root/'music.json')
            self.assertFalse(missing);self.assertEqual(loaded['sequence']['background_audio'],str(root/'assets/music.wav'))
    def test_manual_modes_preserve_long_content_selection(self):
        q=p.defaults();q['output_mode']='both'
        self.assertEqual(s.choose_modes(q,1000,dict(width=1920,height=1080)),['landscape','portrait'])
        q['output_mode']='portrait';self.assertEqual(s.choose_modes(q,1000,dict(width=1920,height=1080)),['portrait'])
    def test_unreviewed_separation_cannot_silently_export(self):
        q=p.defaults();q.update(intro_video=__file__,intro_audio=__file__,intro_srt=__file__,intro_mode='music_voice')
        with self.assertRaisesRegex(ValueError,'试听'):s.opening({'language':'ja'},q,Path('.'),threading.Event(),lambda _:None)

class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.cancel=threading.Event()
        self.clip=self.root/'source.mp4'
        s.ff(['-f','lavfi','-i','color=blue:s=320x180:r=30:d=0.8','-f','lavfi','-i','sine=frequency=440:duration=0.8','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',self.clip],self.cancel)
    def test_cover_first_frame_correct_and_mismatch_requires_choice(self):
        im=self.root/'red.png';Image.new('RGB',(160,90),'red').save(im)
        q=p.defaults();cover=s.cover_clip(str(im),'landscape',q,self.root,self.cancel)
        frame=self.root/'first.png';s.ff(['-i',cover,'-frames:v','1',frame],self.cancel)
        with Image.open(frame) as f:self.assertGreater(f.getpixel((960,540))[0],220)
        with self.assertRaisesRegex(ValueError,'比例'):s.cover_clip(str(im),'portrait',q,self.root,self.cancel)
    def test_vertical_subtitles_and_complete_ending(self):
        q=p.defaults();sub=[(1,0.1,0.7,'金剛経の智慧。')]
        first=s.compose_segment(str(self.clip),sub,{'subtitle_font_size':55},'portrait',q,self.root,self.cancel,True,'body')
        last=s.compose_segment(str(self.clip),[],{},'portrait',q,self.root,self.cancel,False,'ending')
        out=self.root/'joined.mp4';s.concat_clips([first,last],out,self.root,self.cancel)
        data=probe(out,self.cancel);v=next(x for x in data['streams'] if x['codec_type']=='video')
        self.assertEqual((v['width'],v['height']),(1080,1920));self.assertGreater(float(data['format']['duration']),1.5)
        ass=(self.root/'body_portrait.ass').read_text();self.assertIn('金剛経',ass);self.assertIn('\\clip',ass)
    def test_short_opening_voice_keeps_full_music_and_join_timestamps(self):
        voice=self.root/'voice.wav'
        s.ff(['-f','lavfi','-i','sine=frequency=880:duration=0.2',voice],self.cancel)
        refs=self.root/'head.srt';s.write_srt(refs,[(1,.1,.3,'試聴')])
        timing=self.root/'voice.srt';s.write_srt(timing,[(1,0,.18,'試聴')])
        q=p.defaults();q.update(intro_video=str(self.clip),intro_mode='music_voice',intro_audio=str(voice),intro_srt=str(refs),intro_target_srt=str(timing),intro_clean_audio=True)
        mixed,_=s.opening({'language':'ja'},q,self.root,self.cancel,lambda _:None)
        streams=probe(mixed,self.cancel)['streams'];a=next(x for x in streams if x['codec_type']=='audio')
        self.assertAlmostEqual(float(a['duration']),.8,delta=.03)
        joined=self.root/'continuous.mp4';s.concat_clips([mixed,self.clip],joined,self.root,self.cancel)
        from media import run,executable
        packets=json.loads(run([executable('ffprobe'),'-v','error','-select_streams','a:0','-show_packets','-of','json',str(joined)],self.cancel))['packets']
        self.assertLess(max(float(x.get('duration_time',0)) for x in packets),.05)
        times=[float(x['pts_time']) for x in packets];self.assertLess(max(b-a for a,b in zip(times,times[1:])),.05)

    def test_imported_music_replaces_original_without_separation(self):
        music=self.root/'music.wav';s.ff(['-f','lavfi','-i','sine=frequency=660:duration=1',music],self.cancel)
        q=p.defaults();q.update(intro_video=str(self.clip),intro_mode='external_music',background_audio=str(music),intro_clean_audio=False)
        with patch('background_separation.separate',side_effect=AssertionError('must not separate')):
            out,cues=s.opening({'language':'ja'},q,self.root,self.cancel,lambda _:None)
        self.assertFalse(cues)
        from media import executable
        import numpy as np,subprocess
        raw=subprocess.check_output([executable('ffmpeg'),'-v','error','-i',out,'-vn','-ar','8000','-ac','1','-f','f32le','-'])
        samples=np.frombuffer(raw,np.float32);peak=np.argmax(abs(np.fft.rfft(samples)))*8000/len(samples)
        self.assertAlmostEqual(peak,660,delta=3)
        q['background_audio_offset']=.7
        with self.assertRaisesRegex(ValueError,'不会自动循环'):s.imported_background(q,str(self.clip),self.root,self.cancel,lambda _:None)
        q['intro_mode']='original'
        with self.assertRaisesRegex(ValueError,'已导入'):s.opening({'language':'ja'},q,self.root,self.cancel,lambda _:None)
    def test_imported_music_with_voice_skips_original_speech(self):
        music=self.root/'music.wav';voice=self.root/'voice.wav'
        s.ff(['-f','lavfi','-i','sine=frequency=660:duration=1',music],self.cancel)
        s.ff(['-f','lavfi','-i','sine=frequency=880:duration=0.2',voice],self.cancel)
        refs=self.root/'head.srt';s.write_srt(refs,[(1,.1,.3,'試聴')])
        timing=self.root/'voice.srt';s.write_srt(timing,[(1,0,.18,'試聴')])
        q=p.defaults();q.update(intro_video=str(self.clip),intro_mode='music_voice',intro_audio=str(voice),intro_srt=str(refs),intro_target_srt=str(timing),background_audio=str(music))
        with patch('background_separation.separate',side_effect=AssertionError('must not separate')):
            out,cues=s.opening({'language':'ja'},q,self.root,self.cancel,lambda _:None)
        self.assertEqual(len(cues),1)
        a=next(x for x in probe(out,self.cancel)['streams'] if x['codec_type']=='audio');self.assertAlmostEqual(float(a['duration']),.8,delta=.03)

    def test_repair_needs_review_and_never_crops(self):
        q=p.defaults()['layouts']['landscape'];q['repair_roi']='20,120,280,30'
        with self.assertRaisesRegex(ValueError,'确认'):s.repair(str(self.clip),q,self.root,self.cancel)
        out=s.repair(str(self.clip),q,self.root,self.cancel,preview=True,length=.3)
        stream=next(x for x in probe(out,self.cancel)['streams'] if x['codec_type']=='video')
        self.assertEqual((stream['width'],stream['height']),(320,180))
    def test_combined_file_requires_explicit_ending_and_rejects_duplicate(self):
        q=p.defaults();j={'video':str(self.clip)}
        with self.assertRaisesRegex(ValueError,'指定'):s.split_combined(j,q,self.root,self.cancel,lambda _:None)
        q.update(combined_outro_start=.5,outro_enabled=True,outro_video=str(self.clip))
        with self.assertRaisesRegex(ValueError,'重复'):s.split_combined(j,q,self.root,self.cancel,lambda _:None)
    def test_real_pipeline_dual_covers_dissolve_and_audio_cache(self):
        ref=self.root/'ref.srt';ref.write_text('1\n00:00:00,100 --> 00:00:00,700\n金剛経。\n',encoding='utf8')
        wide=self.root/'wide.png';tall=self.root/'tall.png'
        Image.new('RGB',(160,90),'red').save(wide);Image.new('RGB',(90,160),'green').save(tall)
        q=p.defaults();q.update(output_mode='both',intro_enabled=True,intro_video=str(self.clip),outro_enabled=True,outro_video=str(self.clip),cover_landscape=str(wide),cover_portrait=str(tall),cover_seconds=2,cover_transition='dissolve')
        q['layouts']['landscape']['remove_chinese']=False
        job=dict(video=str(self.clip),audio=str(self.clip),source_srt=str(ref),target_srt=str(ref),alignment='timed',language='ja',speed=1,trim=False,burn=False,output=str(self.root/'out'),sequence=q,publish_settings={},name='test')
        folder=Path(s.process(job,self.cancel))
        report=json.loads((folder/'report.json').read_text());self.assertEqual(len(report['results']),2)
        for result in report['results']:
            self.assertGreater(result['duration'],4.2);self.assertLess(result['duration'],4.8)
            self.assertTrue(Path(result['path']).is_file())
        cache=list((self.root/'out/.yangning_cache').rglob('analysis.json'));self.assertEqual(len(cache),1)
        # A style-only change must reuse the exact existing audio/timing result.
        before=cache[0].stat().st_mtime_ns
        j={**job,'publish_settings':{'title':''},'burn':False}
        cached=s.aligned(j,self.root/'out/.yangning_cache',self.cancel,lambda _:None)
        self.assertEqual((cached/'analysis.json').stat().st_mtime_ns,before)
    def test_complete_mp4_protects_explicit_ending(self):
        full=self.root/'full.mp4';s.concat_clips([self.clip,self.clip,self.clip],full,self.root,self.cancel)
        voice=self.root/'voice.wav';s.ff(['-i',full,'-t','1.6','-c:a','pcm_s16le',voice],self.cancel)
        ref=self.root/'ref.srt';ref.write_text('1\n00:00:00,100 --> 00:00:00,700\n第一句。\n\n2\n00:00:00,900 --> 00:00:01,500\n第二句。\n',encoding='utf8')
        q=p.defaults();q.update(output_mode='portrait',combined=True,combined_outro_start=1.6)
        job=dict(video=str(full),audio=str(voice),source_srt=str(ref),target_srt=str(ref),alignment='timed',language='ja',speed=1,trim=False,burn=False,output=str(self.root/'combined_out'),sequence=q,name='combined')
        folder=Path(s.process(job,self.cancel));report=json.loads((folder/'report.json').read_text())
        self.assertGreater(report['results'][0]['duration'],2.3)
        self.assertLess(report['results'][0]['duration'],2.7)
        # An SRT ending at 1.5 sec cannot truncate the music-only ending.
        self.assertGreater(report['results'][0]['duration'],1.5+.7)
        q.update(combined_intro_end=.8,combined_audio_split=.8,intro_clean_audio=True)
        split=self.root/'split';split.mkdir()
        body,parts=s.split_combined(job,q,split,self.cancel,lambda _:None)
        self.assertEqual(len(parse_srt(parts['intro_srt'])),1)
        self.assertEqual(len(parse_srt(body['source_srt'])),1)
        self.assertAlmostEqual(s.seconds(parts['outro_video'],self.cancel),.8,delta=.1)
    def test_phone_tail_metadata_cannot_request_nonexistent_frames(self):
        from engine import prepare,render
        ref=self.root/'tail.srt';ref.write_text('1\n00:00:00,100 --> 00:00:00,700\n正文。\n',encoding='utf8')
        job=dict(video=str(self.clip),audio=str(self.clip),source_srt=str(ref),target_srt=str(ref),alignment='timed',language='ja',speed=1,trim=False,burn=False,output=str(self.root/'tail_out'))
        folder=Path(prepare(job,self.cancel));meta=json.loads((folder/'analysis.json').read_text());meta['video_duration']+=2/30
        (folder/'analysis.json').write_text(json.dumps(meta))
        render(folder,self.cancel)
        report=json.loads((folder/'report.json').read_text())
        self.assertEqual(report['decoded_source_frames'],24);self.assertTrue(report['full_decode_passed'])

if __name__=='__main__':unittest.main()
