"""Fetch exact OFL fonts used by the desktop package; verify content digests."""
import hashlib,urllib.request
from pathlib import Path
FONTS=[
('NotoSerifCJKjp-Regular.otf','https://raw.githubusercontent.com/notofonts/noto-cjk/main/Serif/OTF/Japanese/NotoSerifCJKjp-Regular.otf','d9854c7a8ef170b5a7932558856fd64eb8de0b007cd823fed6f9f514ad2803d3'),
('YujiBoku-Regular.ttf','https://raw.githubusercontent.com/google/fonts/main/ofl/yujiboku/YujiBoku-Regular.ttf','94fda16384f3bdac24376a000c57e99abfa314961bd89ef27badfb7410322003')]
folder=Path(__file__).resolve().parent.parent/'program/fonts'
folder.mkdir(parents=True,exist_ok=True)
for name,url,digest in FONTS:
    target=folder/name
    if not target.exists():target.write_bytes(urllib.request.urlopen(url,timeout=60).read())
    if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise RuntimeError('Font checksum mismatch: '+name)
    print('Font verified:',name)
