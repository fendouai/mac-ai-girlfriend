import asyncio,time
import httpx,numpy as np,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
import os
os.chdir(ROOT)
sys.path.insert(0,str(ROOT/'src'))
from audio_utils import numpy_to_wav_bytes
from aiortc import RTCPeerConnection,RTCSessionDescription,RTCConfiguration
async def main():
 pc=RTCPeerConnection(RTCConfiguration(iceServers=[]));energies=[];times=[];tasks=[];video=0
 @pc.on('track')
 def track(t):
  async def consume():
   nonlocal video
   while True:
    f=await t.recv()
    if t.kind=='audio':energies.append(float(np.sqrt(np.mean(f.to_ndarray().astype(float)**2))));times.append(time.perf_counter())
    else:
     video+=1
     if video == 50:
      import cv2
      Path('logs').mkdir(exist_ok=True)
      cv2.imwrite('logs/avatar-runtime.png',f.to_ndarray(format='bgr24'))
      print('Decoded video:',f.width,'x',f.height,flush=True)
  tasks.append(asyncio.create_task(consume()))
 pc.addTransceiver('video',direction='recvonly');pc.addTransceiver('audio',direction='recvonly')
 try:
  await pc.setLocalDescription(await pc.createOffer())
  async with httpx.AsyncClient(timeout=60) as c:
   r=await c.post('http://127.0.0.1:7860/lt/offer',json={'sdp':pc.localDescription.sdp,'type':'offer'});r.raise_for_status();a=r.json()
   await pc.setRemoteDescription(RTCSessionDescription(sdp=a['sdp'],type=a['type']))
   await asyncio.sleep(1)
   signal=.2*np.sin(np.arange(16000*8)*2*np.pi*220/16000)
   r=await c.post('http://127.0.0.1:8010/humanaudio',data={'sessionid':a['sessionid']},files={'file':('tone.wav',numpy_to_wav_bytes(signal,16000),'audio/wav')});print('uploaded',r.status_code,flush=True)
   await asyncio.sleep(15)
  live=np.flatnonzero(np.array(energies)>200)
  assert len(live)>100,(len(live),len(energies))
  start,end=live[0],live[-1];gaps=np.array(energies[start:end+1])<200
  longest=cur=0
  for gap in gaps:cur=cur+1 if gap else 0;longest=max(longest,cur)
  assert longest <= 2, f'Unexpected audio gap: {longest*20}ms'
  assert abs((times[end]-times[start])-8) < .25, 'Audio was stretched'
  print('active span',times[end]-times[start],'seconds; inserted silent frames',sum(gaps),'max gap ms',longest*20,'video frames',video,flush=True)
 finally:
  await pc.close()
  if 'a' in locals() and a.get('sessionid'):
   async with httpx.AsyncClient(timeout=10) as cleanup:
    response=await cleanup.post('http://127.0.0.1:7860/lt/close_session',json={'sessionid':a['sessionid']})
    response.raise_for_status()
  for t in tasks:t.cancel()
asyncio.run(main())
