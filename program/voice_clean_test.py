import unittest,tempfile,threading,hashlib
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scipy.io import wavfile
from voice_clean import process_wav
from media import Cancelled

class VoiceTests(unittest.TestCase):
    def test_noise_reduction_preserves_timing_soft_voice_and_source(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);r=24000;t=np.arange(r*4)/r;rng=np.random.default_rng(91)
            voice=(.13*np.sin(2*np.pi*190*t)+.06*np.sin(2*np.pi*380*t))
            voice*=((t>1)&(t<3));noise=rng.normal(0,.004,len(t))
            x=(voice+noise).astype('float32');x[int(r*3.5)]=.8
            source=p/'original.wav';target=p/'enhanced.wav';wavfile.write(source,r,x)
            before=hashlib.sha256(source.read_bytes()).digest()
            report=process_wav(source,target,{'audio_profile':'v11'},threading.Event())
            rr,y=wavfile.read(target)
            self.assertEqual(rr,r);self.assertEqual(y.shape,x.shape)
            self.assertEqual(before,hashlib.sha256(source.read_bytes()).digest())
            gap=slice(int(.4*r),int(.8*r));speech=slice(int(1.4*r),int(2.6*r))
            self.assertLess(np.sqrt(np.mean(y[gap]**2)),np.sqrt(np.mean(x[gap]**2))*.8)
            self.assertGreater(np.corrcoef(voice[speech],y[speech])[0,1],.85)
            self.assertGreater(np.sqrt(np.mean(y[speech]**2)),np.sqrt(np.mean(voice[speech]**2))*.65)
            self.assertLess(np.max(np.abs(y[int(3.45*r):int(3.55*r)])),.4)
            self.assertTrue(report['enabled']);self.assertIsNone(report['separation'])
    def test_broadband_alignment_and_tail_at_common_rates(self):
        from scipy.signal import correlate,correlation_lags
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'original.wav';b=Path(d)/'enhanced.wav'
            for rate in (16000,44100,48000):
                with self.subTest(rate=rate):
                    x=np.random.default_rng(rate).normal(0,.07,rate).astype('float32')
                    wavfile.write(a,rate,x)
                    process_wav(a,b,{'audio_profile':'v11'},threading.Event())
                    _,y=wavfile.read(b)
                    lag=correlation_lags(len(y),len(x))[np.argmax(correlate(y,x))]
                    self.assertLessEqual(abs(lag),1)
                    self.assertGreater(np.mean(y[-rate//50:]**2),np.mean(x[-rate//50:]**2)*.25)
    def test_project_export_uses_cleaned_audio_and_preserves_timeline(self):
        import clean_project as cp
        import clean_project_test as fixtures
        fixtures.CleanTests.setUpClass()
        try:
            f=fixtures.CleanTests
            folder=Path(cp.prepare(dict(video=str(f.video),source_srt=str(f.srt),output=str(f.root),auto_cut=False,audio_profile='v11_deep'),f.cancel,make_previews=False))
            m=cp.load(folder);self.assertTrue(m['denoise']['enabled'])
            self.assertEqual(m['cues'],m['adjusted'])
            _,a=wavfile.read(folder/'original.wav');_,b=wavfile.read(folder/'edited.wav')
            self.assertEqual(a.shape,b.shape)
            path=cp.export(folder,f.cancel);self.assertTrue(Path(path).is_file())
        finally:fixtures.CleanTests.tearDownClass()
    def test_opt_in_and_cancel(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'original.wav';b=Path(d)/'enhanced.wav';wavfile.write(a,24000,np.zeros(24000,dtype='float32'))
            with patch('voice_clean.isolate',side_effect=AssertionError('must be opt-in')):
                self.assertFalse(process_wav(a,b,{'denoise':True,'separate':True},threading.Event())['enabled'])
            self.assertEqual(a.read_bytes(),b.read_bytes())
            cancel=threading.Event();cancel.set()
            with self.assertRaises(Cancelled):process_wav(a,b,{'audio_profile':'v11'},cancel)
            with self.assertRaises(ValueError):process_wav(a,a,{},threading.Event())
    def test_explicit_separation_is_independent_and_failure_is_visible(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'original.wav';b=Path(d)/'enhanced.wav';wavfile.write(a,24000,np.zeros(24000,dtype='float32'))
            with patch('voice_clean.isolate',side_effect=RuntimeError('model failed')) as isolate:
                with self.assertRaisesRegex(RuntimeError,'model failed'):process_wav(a,b,{'audio_profile':'v11','audio_separate':True},threading.Event())
                isolate.assert_called_once()
            self.assertFalse(b.exists())


class DeepVoiceTests(unittest.TestCase):
    def test_rnnoise_preserves_channels_duration_and_last_voice(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            for rate,channels in ((16000,1),(24000,1),(44100,2),(48000,2)):
                with self.subTest(rate=rate,channels=channels):
                    t=np.arange(rate*2+17)/rate
                    phase=2*np.pi*(160*t+25*t*t)
                    x=sum(.1/k*np.sin(k*phase) for k in range(1,7));x[:rate//2]=0
                    if channels==2:x=np.stack([x,x*.7],axis=1)
                    x=x.astype('float32');a=p/'原声.wav';b=p/'处理.wav';wavfile.write(a,rate,x)
                    before=hashlib.sha256(a.read_bytes()).hexdigest()
                    report=process_wav(a,b,{'audio_profile':'v11_deep'},threading.Event())
                    rr,y=wavfile.read(b)
                    self.assertEqual((rr,y.shape),(rate,x.shape));self.assertTrue(np.isfinite(y).all())
                    self.assertEqual(before,hashlib.sha256(a.read_bytes()).hexdigest())
                    self.assertGreater(np.max(np.abs(y[-rate//50:])),.001)
                    from scipy.signal import correlate,correlation_lags
                    xx=x if channels==1 else x[:,0];yy=y if channels==1 else y[:,0]
                    lag=correlation_lags(len(yy),len(xx))[np.argmax(correlate(yy,xx))]
                    self.assertLessEqual(abs(lag),rate*.001)
                    self.assertEqual(report['latency_sample_rate'],48000)
                    self.assertTrue(report['manual_phrase_review_required']);self.assertFalse(report['semantic_noise_removal'])
    def test_missing_deep_model_fails_visibly(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'a.wav';b=Path(d)/'b.wav';wavfile.write(a,24000,np.zeros(24000,dtype='float32'))
            with patch('voice_clean.MODEL_DIGEST','invalid'):
                with self.assertRaisesRegex(RuntimeError,'模型缺失或校验失败'):
                    process_wav(a,b,{'audio_profile':'v11_deep'},threading.Event())
            self.assertFalse(b.exists())

if __name__=='__main__':unittest.main()
