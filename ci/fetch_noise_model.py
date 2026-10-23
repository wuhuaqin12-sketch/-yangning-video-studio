"""Fetch the exact model used in the V11 review into distributable assets."""
import hashlib,urllib.request
from pathlib import Path
DIGEST='ae3f7411e1e6a884f839a4a145c394408398f09854dbc1216ee02faafc98a17b'
URL='https://raw.githubusercontent.com/richardpl/arnndn-models/0fda24c46d78f0207d820bb970fbe85c1971b39c/bd.rnnn'
target=Path(__file__).resolve().parent.parent/'program/models/bd.rnnn'
target.parent.mkdir(parents=True,exist_ok=True)
if not target.exists():target.write_bytes(urllib.request.urlopen(URL,timeout=60).read())
if hashlib.sha256(target.read_bytes()).hexdigest()!=DIGEST:raise RuntimeError('RNNoise model checksum mismatch')
print('V11 RNNoise model verified')
