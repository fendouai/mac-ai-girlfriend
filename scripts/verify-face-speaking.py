"""Receive actual spoken face video; check motion, preserved nose and frame rate."""
import asyncio
import json
from pathlib import Path
import time
import sys

import cv2
import httpx
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration

ROOT = Path(__file__).resolve().parents[1]
profiles = json.loads((ROOT / 'data/avatars/mouth-profiles.json').read_text())['avatars']


async def check(client, name, profile):
    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    tasks=[];sid=None;times=[];nose_errors=[];body_errors=[];mouth_frames=[];energies=[]
    reference=cv2.imread(str(ROOT / 'third_party/livetalking/data/avatars' / name / 'full_imgs/00000000.png'))
    cx,cy=(np.array(profile['center'])*[768,1024]).astype(int)
    span=profile['width']*768;nose_bottom=int(profile['nose_floor']*1024)-4
    nose=(slice(nose_bottom-23,nose_bottom),slice(int(cx-span*.27),int(cx+span*.27)))
    mouth=(slice(cy-12,cy+int(span*.35)),slice(cx-int(span*.5),cx+int(span*.5)))
    best_change=0;best_image=None
    @pc.on('track')
    def track(track):
        async def consume():
            nonlocal best_change,best_image
            while True:
                frame=await track.recv()
                if track.kind=='audio':
                    energies.append(float(np.sqrt(np.mean(frame.to_ndarray().astype(float)**2))))
                else:
                    times.append(time.perf_counter());image=frame.to_ndarray(format='bgr24')
                    assert image.shape==reference.shape
                    nose_errors.append(float(np.mean(abs(image[nose].astype(float)-reference[nose]))))
                    body_errors.append(float(np.mean(abs(image[650:950,100:680].astype(float)-reference[650:950,100:680]))))
                    mouth_frames.append(image[mouth].astype(float))
                    change=float(np.mean(abs(image[mouth].astype(float)-reference[mouth])))
                    if change>best_change:
                        best_change=change
                        best_image=image.copy()
        tasks.append(asyncio.create_task(consume()))
    pc.addTransceiver('video',direction='recvonly');pc.addTransceiver('audio',direction='recvonly')
    try:
        await pc.setLocalDescription(await pc.createOffer())
        response=await client.post('http://127.0.0.1:7860/lt/offer',json=dict(sdp=pc.localDescription.sdp,type='offer',avatar=name))
        response.raise_for_status();answer=response.json();sid=answer['sessionid']
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type=answer['type']))
        await asyncio.sleep(1)
        fixture=(ROOT / 'logs/mouth-test-speech.wav').read_bytes()
        response=await client.post('http://127.0.0.1:8010/humanaudio',data={'sessionid':sid},files={'file':('speech.wav',fixture,'audio/wav')})
        response.raise_for_status();await asyncio.sleep(8)
        for task in tasks:
            if task.done():task.result()
        fps=(len(times)-1)/(times[-1]-times[0])
        movement=float(np.abs(np.diff(np.array(mouth_frames),axis=0)).mean())
        assert 23<fps<27,(name,fps)
        assert np.mean(nose_errors)<6 and np.mean(body_errors)<8,(nose_errors,body_errors)
        assert movement>.6 and best_change>4,(movement,best_change)
        assert max(energies)>200,'Decoded audio is silent'
        cv2.imwrite(str(ROOT / 'logs' / f'{name}-speaking-new.png'),best_image)
        print(json.dumps(dict(avatar=name,passed=True,decoded_fps=fps,video_frames=len(times),
                              nose_mae=float(np.mean(nose_errors)),body_mae=float(np.mean(body_errors)),
                              mouth_frame_difference=movement,peak_audio_rms=max(energies))),flush=True)
    finally:
        await pc.close()
        for task in tasks:task.cancel()
        if sid:
            response=await client.post('http://127.0.0.1:7860/lt/close_session',json={'sessionid':sid});response.raise_for_status()


async def main():
    fixture=ROOT / 'logs/mouth-test-speech.wav'
    if not fixture.exists():
        fixture.parent.mkdir(exist_ok=True)
        sys.path.insert(0,str(ROOT / 'third_party/livetalking'))
        from avatars.wav2lip import audio
        wave=audio.load_wav(str(ROOT / 'data/prompt1.mp3'),16000)[:64000]
        audio.save_wav(wave.copy(),str(fixture),16000)
    async with httpx.AsyncClient(timeout=60) as client:
        for name,profile in profiles.items():await check(client,name,profile)


asyncio.run(main())
