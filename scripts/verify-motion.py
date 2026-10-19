"""Check decoded idle motion without feeding any speech; save a visual preview."""
import asyncio
from pathlib import Path
import cv2
import httpx
import numpy as np
from PIL import Image
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration

ROOT = Path(__file__).resolve().parents[1]

async def main():
    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    samples, tasks = [], []

    @pc.on('track')
    def track(t):
        async def consume():
            count = 0
            while True:
                frame = await t.recv()
                if t.kind == 'video':
                    count += 1
                    if count % 5 == 0:
                        samples.append(cv2.resize(frame.to_ndarray(format='bgr24'), (352, 360)))
        tasks.append(asyncio.create_task(consume()))

    pc.addTransceiver('video', direction='recvonly')
    pc.addTransceiver('audio', direction='recvonly')
    try:
        await pc.setLocalDescription(await pc.createOffer())
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post('http://127.0.0.1:7860/lt/offer', json={
                'sdp': pc.localDescription.sdp, 'type': 'offer'})
            response.raise_for_status()
            answer = response.json()
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'], type=answer['type']))
        await asyncio.sleep(7)
        assert len(samples) >= 25, f'Insufficient decoded frames: {len(samples)}'
        # This region covers shoulders/clothing, outside the synthesized mouth.
        reference = samples[0][230:350, 60:290].astype(float)
        motion = max(float(np.mean(abs(im[230:350, 60:290].astype(float) - reference))) for im in samples)
        assert motion > 1.0, f'No meaningful idle body motion: {motion}'
        output = ROOT / 'logs'
        output.mkdir(exist_ok=True)
        images = [Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)) for im in samples[:30]]
        images[0].save(output / 'avatar-idle.gif', save_all=True, append_images=images[1:], duration=200, loop=0)
        indices = np.linspace(0, len(samples)-1, 6).astype(int)
        cv2.imwrite(str(output / 'avatar-idle-contact.jpg'), np.concatenate([samples[i] for i in indices], axis=1))
        print(f'PASS: {len(samples)} decoded idle samples; shoulder/body change MAE {motion:.2f}; logs/avatar-idle.gif')
    finally:
        await pc.close()
        if 'answer' in locals() and answer.get('sessionid'):
            async with httpx.AsyncClient(timeout=10) as cleanup:
                response=await cleanup.post('http://127.0.0.1:7860/lt/close_session',json={'sessionid':answer['sessionid']})
                response.raise_for_status()
        for task in tasks:
            task.cancel()

asyncio.run(main())
