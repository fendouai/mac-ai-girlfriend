import os, requests, struct, concurrent.futures, pathlib, zlib as zl
os.chdir(pathlib.Path(__file__).resolve().parents[1])
from remotezip import RemoteZip
url='https://hf-mirror.com/datasets/hexgeek/hex-ai-girlfriend-datasets/resolve/main/models.zip'
with RemoteZip(url) as z:
 infos=[f for f in z.infolist() if not f.is_dir() and (f.filename == 'models/wav2lip256.pth' or any(f.filename.startswith(p) for p in ['models/CosyVoice2-0.5B/','models/SenseVoiceSmall/','models/wetext/']))]
chunk=16*1024*1024
folder=pathlib.Path('models/.download-parts');folder.mkdir(exist_ok=True)
jobs=[];entries=[]
for index,info in enumerate(infos):
 print("Preparing",info.filename,flush=True)
 target=pathlib.Path(info.filename)
 if target.exists() and target.stat().st_size == info.file_size:
  crc=0
  with target.open('rb') as existing:
   for data in iter(lambda: existing.read(8388608), b''):crc=zl.crc32(data,crc)
  if crc == info.CRC:
   print('Already verified',info.filename,flush=True);continue
 if pathlib.PurePosixPath(info.filename).is_absolute() or ".." in pathlib.PurePosixPath(info.filename).parts:raise ValueError("Invalid archive path")
 r=requests.get(url,params={'header':index},headers={'Range':f'bytes={info.header_offset}-{info.header_offset+511}'},timeout=45);r.raise_for_status();assert r.status_code==206
 h=struct.unpack('<4s5H3I2H',r.content[:30]);start=info.header_offset+30+h[-2]+h[-1]
 count=(info.compress_size+chunk-1)//chunk
 entries.append((info,index,count))
 for part in range(count):jobs.append((index,part,start+part*chunk,min(chunk,info.compress_size-part*chunk)))
print('entries',len(entries),'download bytes',sum(i.compress_size for i,_,_ in entries),flush=True)
def get(job):
 index,part,start,n=job;p=folder/f'{index}-{part}'
 if p.exists() and p.stat().st_size==n:return
 for attempt in range(4):
  try:
   blocks=[]
   for offset in range(0,n,8388608):
    count=min(8388608,n-offset)
    r=requests.get(url,params={'hexmodel':f'{index}-{part}-{offset}'},headers={'Range':f'bytes={start+offset}-{start+offset+count-1}'},timeout=120)
    assert r.status_code==206 and len(r.content)==count,(r.status_code,len(r.content),count)
    blocks.append(r.content)
   temp=p.with_suffix('.partial');temp.write_bytes(b''.join(blocks));temp.replace(p)
   print('part',index,part,flush=True);return
  except Exception:
   if attempt==3:raise
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:list(pool.map(get,jobs))
for info,index,count in entries:
 target=pathlib.Path(info.filename);target.parent.mkdir(parents=True,exist_ok=True)
 dec=zl.decompressobj(-15) if info.compress_type==8 else None;crc=0;size=0
 temp=target.with_suffix(target.suffix+'.partial')
 with temp.open('wb') as out:
  for part in range(count):
   b=(folder/f'{index}-{part}').read_bytes();data=dec.decompress(b) if dec else b;crc=zl.crc32(data,crc);size+=len(data);out.write(data)
  if dec:
   data=dec.flush();crc=zl.crc32(data,crc);size+=len(data);out.write(data)
 assert crc==info.CRC and size==info.file_size,info.filename
 temp.replace(target)
 print('verified',info.filename,flush=True)
