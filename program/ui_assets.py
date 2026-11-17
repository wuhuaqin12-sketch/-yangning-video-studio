"""Small UI asset checks and explicit persistent intro-music preferences."""
import json
from pathlib import Path
from PIL import Image
from desktop_update import atomic_json

def check_image(path,label='图片'):
    path=Path(path)
    try:
        with Image.open(path) as im:
            if im.format not in ('JPEG','PNG'):raise ValueError('请使用JPG或PNG图片。')
            im.verify()
    except Exception as e:
        raise ValueError(label+'需要可读取的JPG或PNG图片，不能放入MP4视频。') from e
    return str(path)

def filetypes(key):
    if key in ('background','cover','cover_landscape','cover_portrait'):return [('JPG / PNG 图片','*.jpg *.jpeg *.png')]
    if 'srt' in key:return [('SRT 字幕','*.srt')]
    if key in ('audio','intro_audio','background_audio'):return [('配音 / 音乐','*.wav *.mp3 *.m4a *.aac *.flac *.mp4 *.mov')]
    return [('视频','*.mp4 *.mov *.mkv *.avi *.m4v')]

def load_music(data):
    try:return str(json.loads((Path(data)/'intro_music_preferences.json').read_text(encoding='utf8'))['path'])
    except (OSError,ValueError,KeyError,TypeError):return ''

def remember_music(data,path):
    if path and not Path(path).is_file():raise ValueError('片头背景音乐文件不存在，请重新选择。')
    atomic_json(Path(data)/'intro_music_preferences.json',dict(schema=1,path=str(Path(path).resolve()) if path else ''))

def load_outro(data):
    try:return str(json.loads((Path(data)/'fixed_outro_preferences.json').read_text(encoding='utf8'))['path'])
    except (OSError,ValueError,KeyError,TypeError):return ''

def remember_outro(data,path):
    if path and not Path(path).is_file():raise ValueError('固定片尾视频不存在，请重新选择。')
    atomic_json(Path(data)/'fixed_outro_preferences.json',dict(schema=1,path=str(Path(path).resolve()) if path else ''))
