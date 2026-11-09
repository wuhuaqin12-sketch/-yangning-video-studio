import hashlib
import tempfile
import unittest
import wave
from pathlib import Path
import numpy as np
from voice_adjust import adjust_audio, interpret_instruction, style_instruction

class AdjustTests(unittest.TestCase):
    def test_explicit_instruction_routing(self):
        result=interpret_instruction('放慢一点，更柔和，轻度降噪，变成另一个人')
        self.assertEqual(result['tempo'],.9)
        self.assertEqual(result['styles'],['更柔和'])
        self.assertTrue(result['denoise'])
        self.assertEqual(result['unrecognized'],['变成另一个人'])
        with self.assertRaises(ValueError): style_instruction(['未支持'])

    def test_preserves_source_silence_pitch_and_duration(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'original.wav'
            rate=48000
            samples=np.concatenate([np.zeros(rate//2),.2*np.sin(2*np.pi*220*np.arange(rate)/rate),np.zeros(rate//2)])
            with wave.open(str(p),'wb') as w:
                w.setparams((1,2,rate,0,'NONE','not compressed'));w.writeframes((samples*32767).astype('<i2').tobytes())
            before=hashlib.sha256(p.read_bytes()).hexdigest()
            target=Path(adjust_audio(p,td,.9,2,False))
            self.assertEqual(before,hashlib.sha256(p.read_bytes()).hexdigest())
            with wave.open(str(target),'rb') as w:
                audio=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2')/32768
            self.assertAlmostEqual(len(audio)/rate,2/.9,delta=.04)
            self.assertLess(np.max(np.abs(audio[:rate//4])),.002)
            mid=audio[rate:rate+12000]
            frequency=np.argmax(np.abs(np.fft.rfft(mid)))*rate/len(mid)
            self.assertAlmostEqual(frequency,220,delta=5)
            self.assertLessEqual(np.max(np.abs(audio)),.951)
            self.assertTrue((target.parent/'adjustment.json').is_file())

if __name__=='__main__': unittest.main()
