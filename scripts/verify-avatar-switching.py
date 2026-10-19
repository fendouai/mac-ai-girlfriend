"""Exercise real offers/releases repeatedly and check both facial identities."""
import asyncio
from pathlib import Path
import cv2,httpx,numpy as np
from aiortc import RTCPeerConnection,RTCSessionDescription,RTCConfiguration
ROOT=Path(__file__).resolve().parents[1]

async def check(client,name):
    pc=RTCPeerConnection(RTCConfiguration(iceServers=[]));image_ready=asyncio.get_running_loop().create_future();tasks=[];sessionid=None
    @pc.on('track')
    def track(t):
        async def consume():
            count=0
            while True:
                frame=await t.recv()
                if t.kind=='video':
                    count+=1
                    if count==20 and not image_ready.done():image_ready.set_result(frame.to_ndarray(format='bgr24'))
        tasks.append(asyncio.create_task(consume()))
    pc.addTransceiver('video',direction='recvonly');pc.addTransceiver('audio',direction='recvonly')
    try:
        await pc.setLocalDescription(await pc.createOffer())
        response=await client.post('http://127.0.0.1:7860/lt/offer',json={'sdp':pc.localDescription.sdp,'type':'offer','avatar':name})
        response.raise_for_status();answer=response.json();assert answer.get('sdp'),answer
        sessionid=answer['sessionid']
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type=answer['type']))
        image=await asyncio.wait_for(image_ready,20)
        reference=cv2.imread(str(ROOT/'third_party/livetalking/data/avatars'/name/'full_imgs/00000000.png'))
        assert image.shape==reference.shape,(image.shape,reference.shape)
        error=float(np.mean(abs(image[650:1000,100:680].astype(float)-reference[650:1000,100:680].astype(float))))
        assert error<8,f'Wrong identity or poor decoded image: body MAE {error}'
        cv2.imwrite(str(ROOT/'logs'/f'{name}-received.png'),image)
        print(f'PASS: {name}; actual decoded identity body MAE {error:.3f}; {sessionid}',flush=True)
    finally:
        if sessionid:
            response=await client.post('http://127.0.0.1:7860/lt/close_session',json={'sessionid':sessionid});response.raise_for_status();assert response.json()['code']==0
        await pc.close()
        for task in tasks:task.cancel()

async def main():
    async with httpx.AsyncClient(timeout=60) as client:
        for name in ['hex_clean_original','hex_clean_sweet','hex_clean_original']:
            await check(client,name)
    print('PASS: repeated original → sweet → original switches without exhausting the two-session limit',flush=True)
asyncio.run(main())
