"""Exercise the actual optional CPU model and sample-preserving output in CI."""
import sys,tempfile,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'program'))
import numpy as np
from scipy.io import wavfile
from voice_clean import process_wav
with tempfile.TemporaryDirectory() as d:
    root=Path(d)
    import app as ui
    ui.DATA=root;ui.STATE=root/'test_queue.json'
    window=ui.tk.Tk();window.withdraw()
    application=ui.App(window);application.sound_settings();window.update_idletasks()
    assert any(isinstance(child,ui.tk.Toplevel) for child in window.winfo_children())
    def widgets(parent):
        for child in parent.winfo_children():
            yield child
            yield from widgets(child)
    preset=next(w for w in widgets(window) if isinstance(w,ui.ttk.Button) and str(w.cget('text')).startswith('按本次标准设置'))
    preset.invoke()
    assert application.v['audio_profile'].get()=='v11_deep'
    assert application.v['audio_separate'].get()
    application.sound_rules();window.update_idletasks()
    assert any(isinstance(w,ui.tk.Text) and 'RNNoise' in w.get('1.0','end') for w in widgets(window))
    window.destroy()
    print('WINDOWS_SOUND_SETTINGS_UI_PASS')
    r=24000;t=np.arange(r*2)/r
    x=(.1*np.sin(2*np.pi*180*t)+.015*np.sin(2*np.pi*600*t)).astype('float32')
    wavfile.write(root/'original.wav',r,x)
    report=process_wav(root/'original.wav',root/'enhanced.wav',{'audio_profile':'v11_deep','audio_separate':True},threading.Event(),print)
    rr,y=wavfile.read(root/'enhanced.wav')
    assert rr==r and x.shape==y.shape and np.isfinite(y).all()
    assert report['separation']['model']=='htdemucs'
    print('REAL_CPU_SEPARATION_AND_DENOISE_PASS')
