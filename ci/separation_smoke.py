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
    frames = [str(w.cget('text')) for w in widgets(window) if isinstance(w, ui.ttk.LabelFrame)]
    assert '①  选择素材' in frames
    assert '②  一键生成' in frames
    preset=next(w for w in widgets(window) if isinstance(w,ui.ttk.Button) and str(w.cget('text'))=='一键降噪并生成试听')
    from unittest.mock import patch
    with patch.object(ui.messagebox,'showinfo'):
        preset.invoke()
    assert application.v['audio_profile'].get()=='v11_deep'
    assert application.v['audio_separate'].get()
    assert any(isinstance(w,ui.ttk.Entry) and str(w.cget('textvariable'))==str(application.v['audio_reference_srt']) for w in widgets(window))
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
    assert (root/'声音处理报告.json').is_file()
    print('REAL_CPU_SEPARATION_AND_DENOISE_PASS')
