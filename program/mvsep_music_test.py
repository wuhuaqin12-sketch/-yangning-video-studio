import io,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import mvsep_music as m
class Contract(unittest.TestCase):
    def test_official_model(self):
        data=json.loads(Path(__file__).with_name('mvsep_model_fixture.json').read_text(encoding='utf8'))
        self.assertEqual(m.verify_model(data)['render_id'],56)
        data[0]['algorithm_fields'][0]['options']='{"2":"Demucs"}'
        with self.assertRaises(m.CloudError):m.verify_model(data)
    def test_only_music(self):
        files=[{'type':x,'url':'https://sg.mvsep.com/'+x+'.wav'} for x in ['Speech','Music','Sfx']]
        self.assertTrue(m.music_file(files).endswith('/Music.wav'))
        with self.assertRaises(m.CloudError):m.music_file(files+files)
        with self.assertRaises(m.CloudError):m.music_file(files[:1])
        with self.assertRaises(m.CloudError):m.music_file([{'type':'Music','url':'https://example.com/Music.wav'}])
    def test_exact_upload_options(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'audio.wav';p.write_bytes(b'original-data')
            with patch.object(m,'request_json',return_value={'success':True}) as r:m.submit(p,'SECRET',threading.Event(),lambda _:None)
            args=r.call_args;body=b''.join(args.kwargs['body'])
            for k,v in m.OPTIONS.items():self.assertIn(('name="'+k+'"\r\n\r\n'+v+'\r\n').encode(),body)
            self.assertIn(b'original-data',body);self.assertNotIn(b'preset_id',body)
            self.assertEqual(int(args.kwargs['headers']['Content-Length']),len(body))
    def test_no_token_no_request(self):
        with patch.object(m,'request_json') as r:
            with self.assertRaises(m.CloudError):m.check_account('',lambda _:None)
            r.assert_not_called()
    def test_real_mux_and_resume(self):
        cancel=threading.Event()
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=root/'source.mp4';music=root/'fixture.wav';output=root/'out'
            m.run([m.executable('ffmpeg'),'-v','error','-y','-f','lavfi','-i','testsrc2=size=96x64:rate=25','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','2','-c:v','libx264','-c:a','aac',str(source)],cancel)
            duration=float(m.probe(source,cancel)['format']['duration'])
            m.run([m.executable('ffmpeg'),'-v','error','-y','-f','lavfi','-i','sine=frequency=220:sample_rate=44100','-t',str(duration),str(music)],cancel)
            raw=music.read_bytes();submitted=[];polled=[]
            def submit(*args):submitted.append(True);return {'success':True,'data':{'hash':'existing-job'}}
            def request(endpoint,params=None,**kw):
                self.assertEqual(endpoint,'separation/get');polled.append(True)
                if len(polled)==1:raise m.CloudError('network loss')
                return {'success':True,'status':'done','data':{'algorithm':'MVSep DnR v3 (speech, music, effects)','files':[{'type':'Music','url':'https://sg.mvsep.com/music.wav'}]}}
            class Opener:
                def open(self,*a,**kw):return io.BytesIO(raw)
            with patch.object(m,'check_account',return_value={'premium_enabled':0}),patch.object(m,'submit',side_effect=submit),patch.object(m,'request_json',side_effect=request),patch.object(m.urllib.request,'build_opener',return_value=Opener()):
                with self.assertRaises(m.CloudError):m.process(source,output,'SECRET',cancel,lambda _:None)
                result=m.process(source,output,'SECRET',cancel,lambda _:None)
                self.assertEqual(len(submitted),1)
                self.assertEqual(m.video_digest(source,cancel),m.video_digest(result,cancel))
                self.assertNotIn('SECRET',result.with_suffix('.mvsep.json').read_text())
                with self.assertRaises(m.CloudError):m.process(result,output,'SECRET',cancel,lambda _:None)
                preview=m.process(source,output,'SECRET',cancel,lambda _:None,seconds=2)
                self.assertTrue(preview.exists())
    def test_streaming_http_transport(self):
        import http.server
        captured=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                captured.append(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(200);self.end_headers();self.wfile.write(b'{"success": true}')
            def log_message(self,*args):pass
        server=http.server.HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as t:
                p=Path(t)/'audio.wav';p.write_bytes(b'original-data')
                with patch.object(m,'API',f'http://127.0.0.1:{server.server_port}/'):
                    self.assertTrue(m.submit(p,'LOCAL-TEST',threading.Event(),lambda _:None)['success'])
                self.assertIn(b'original-data',captured[0])
        finally:server.shutdown();server.server_close();thread.join()
    def test_wrong_model_and_no_fallback(self):
        with self.assertRaises(m.CloudError):m.verify_model([{'render_id':56,'name':'Demucs'}])
    def test_account_does_not_enable_premium(self):
        fixture=json.loads(Path(__file__).with_name('mvsep_model_fixture.json').read_text(encoding='utf8'))
        with patch.object(m,'request_json',side_effect=[fixture,{'success':True,'data':{'premium_enabled':0,'premium_minutes':0}}]) as request:
            m.check_account('PRIVATE',lambda _:None)
            self.assertEqual([c.args[0] for c in request.call_args_list],['app/algorithms','app/user'])
    def test_https_only(self):
        with self.assertRaises(m.CloudError):m.safe_url('http://mvsep.com/music.wav')
if __name__=='__main__':unittest.main()
