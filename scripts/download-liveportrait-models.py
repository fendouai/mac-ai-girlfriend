"""Fetch original human LivePortrait weights, with resumable verified range parts."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,requests
ROOT=Path(__file__).resolve().parents[1]
repo='KlingTeam/LivePortrait'
revision='82a4fa6735ca58432b6ce39301b4b9ee066dea47'
r=requests.get(f'https://hf-mirror.com/api/models/{repo}/tree/{revision}?recursive=true',timeout=30);r.raise_for_status()
entries=[x for x in r.json() if x['type']=='file' and (x['path'].startswith('liveportrait/') or x['path'].startswith('insightface/'))]
base=ROOT/'third_party/LivePortrait/pretrained_weights';parts=ROOT/'models/.liveportrait-parts';parts.mkdir(parents=True,exist_ok=True)
jobs=[]
for entry in entries:
 target=base/entry['path'];expected=entry.get('lfs',{}).get('oid')
 if target.exists() and target.stat().st_size==entry['size'] and (not expected or hashlib.sha256(target.read_bytes()).hexdigest()==expected):continue
 for start in range(0,entry['size'],4*1024*1024):jobs.append((entry,start,min(entry['size'],start+4*1024*1024)-1))
def fetch(job):
 entry,start,end=job;key=hashlib.sha256(entry['path'].encode()).hexdigest()[:16];part=parts/f'{key}-{start}'
 if part.exists() and part.stat().st_size==end-start+1:return
 for attempt in range(4):
  try:
   response=requests.get(f"https://hf-mirror.com/{repo}/resolve/{revision}/{entry['path']}",params={'hexpart':start},headers={'Range':f'bytes={start}-{end}'},timeout=90)
   response.raise_for_status();assert len(response.content)==end-start+1
   temp=part.with_suffix('.partial');temp.write_bytes(response.content);temp.replace(part);return
  except Exception:
   if attempt==3:raise
with ThreadPoolExecutor(max_workers=8) as pool:
 for index,_ in enumerate(pool.map(fetch,jobs)):
  if index%10==0:print('Downloaded parts',index+1,'/',len(jobs),flush=True)
for entry in entries:
 target=base/entry['path'];expected=entry.get('lfs',{}).get('oid')
 if target.exists() and target.stat().st_size==entry['size'] and (not expected or hashlib.sha256(target.read_bytes()).hexdigest()==expected):continue
 key=hashlib.sha256(entry['path'].encode()).hexdigest()[:16];target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_suffix(target.suffix+'.partial')
 with temp.open('wb') as handle:
  for start in range(0,entry['size'],4*1024*1024):handle.write((parts/f'{key}-{start}').read_bytes())
 assert temp.stat().st_size==entry['size']
 if expected:assert hashlib.sha256(temp.read_bytes()).hexdigest()==expected
 temp.replace(target);print('Verified',entry['path'],flush=True)
(base/'hex-source.json').write_text(json.dumps({'repository':repo,'revision':revision,'files':entries},indent=2)+'\n')
