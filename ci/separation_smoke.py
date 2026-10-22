"""Exercise the actual optional CPU model and sample-preserving output in CI."""
import sys,tempfile,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'program'))
import numpy as np
from scipy.io import wavfile
from voice_clean import process_wav
with tempfile.TemporaryDirectory() as d:
    root=Path(d);r=24000;t=np.arange(r*2)/r
    x=(.1*np.sin(2*np.pi*180*t)+.015*np.sin(2*np.pi*600*t)).astype('float32')
    wavfile.write(root/'original.wav',r,x)
    report=process_wav(root/'original.wav',root/'enhanced.wav',{'audio_profile':'v11','audio_separate':True},threading.Event(),print)
    rr,y=wavfile.read(root/'enhanced.wav')
    assert rr==r and x.shape==y.shape and np.isfinite(y).all()
    assert report['separation']['model']=='htdemucs'
    print('REAL_CPU_SEPARATION_AND_DENOISE_PASS')
