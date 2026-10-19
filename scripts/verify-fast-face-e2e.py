"""Actual text -> cloned speech -> LiveTalking -> decoded WebRTC audio/video."""
import asyncio
import base64
import json
from pathlib import Path
import time
import wave

import httpx
import numpy as np
import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration


async def main():
    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    tasks = []
    video_times = []
    energies = []
    audio_times = []
    mouths = []
    sid = None

    @pc.on('track')
    def track(track):
        async def consume():
            while True:
                frame = await track.recv()
                now = time.perf_counter()
                if track.kind == 'audio':
                    energies.append(float(np.sqrt(np.mean(frame.to_ndarray().astype(float)**2))))
                    audio_times.append(now)
                else:
                    image = frame.to_ndarray(format='bgr24')
                    assert image.shape == (1024,768,3), image.shape
                    video_times.append(now)
                    mouths.append(image[395:455,350:455].astype(float))
        tasks.append(asyncio.create_task(consume()))

    pc.addTransceiver('video', direction='recvonly')
    pc.addTransceiver('audio', direction='recvonly')
    results = []

    async def reply(ws, label, started):
        pcm = bytearray()
        first = None
        transcript = ''
        async with asyncio.timeout(60):
            async for raw in ws:
                event = json.loads(raw)
                if event['type'] == 'error':
                    raise RuntimeError(event)
                if event['type'] == 'response.output_audio.delta':
                    first = first or time.perf_counter()
                    pcm.extend(base64.b64decode(event['delta']))
                if event['type'] == 'response.output_audio_transcript.delta':
                    transcript += event.get('delta','')
                if event['type'] == 'response.done':
                    assert first and pcm and event['response']['status']=='completed', event
                    break
        duration = len(pcm)/32000
        await asyncio.sleep(duration+1.2)
        voiced = [t for t,e in zip(audio_times,energies) if t>=started and e>150]
        assert voiced, 'No actual WebRTC voice playback'
        transport_delay = voiced[0]-first
        assert -.1 < transport_delay < 1.5, transport_delay
        with wave.open('logs/optimized-'+label+'.wav','wb') as output:
            output.setparams((1,2,16000,0,'NONE','not compressed'))
            output.writeframes(pcm)
        result = dict(label=label, chars=len(transcript), transcript=transcript,
                      first_pcm_seconds=first-started, first_webrtc_voice_seconds=voiced[0]-started,
                      pcm_to_webrtc_seconds=transport_delay, audio_seconds=duration)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    try:
        await pc.setLocalDescription(await pc.createOffer())
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post('http://127.0.0.1:7860/lt/offer',json={
                'sdp':pc.localDescription.sdp,'type':'offer','avatar':'hex_clean_sweet'})
            response.raise_for_status()
            answer = response.json()
            assert 'sdp' in answer, answer
            sid = answer['sessionid']
            await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type=answer['type']))
            async with websockets.connect('ws://127.0.0.1:7860/v1/realtime') as ws:
                await ws.send(json.dumps({'type':'sessionid','sessionid':sid}))
                started = time.perf_counter()
                await ws.send(json.dumps({'type':'session.update','session':{
                    'avatar_transport':'webrtc','instructions':'你是中文语音测试助手。用户要求原样回复时，只输出指定原文，不加解释。'}}))
                await reply(ws, 'welcome', started)
                for label,text in [('short','你好呀，我在这里陪着你。'),
                                   ('long','今天的天气很好，我们可以一起出去散步，聊聊最近发生的有趣事情，然后找个安静的地方喝杯茶。')]:
                    started = time.perf_counter()
                    await ws.send(json.dumps({'type':'user.text','text':'请原样回复：'+text}))
                    await reply(ws,label,started)
            fps = (len(video_times)-1)/(video_times[-1]-video_times[0])
            movement = float(np.abs(np.diff(np.array(mouths),axis=0)).mean())
            assert 23<fps<27 and movement>.2, (fps,movement)
            for task in tasks:
                if task.done():
                    task.result()
            result = dict(passed=True, decoded_fps=fps, mouth_frame_difference=movement, replies=results)
            Path('logs/fast-face-e2e-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(dict(passed=True, decoded_fps=fps,mouth_frame_difference=movement)),flush=True)
    finally:
        await pc.close()
        if sid:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post('http://127.0.0.1:7860/lt/close_session',json={'sessionid':sid})
                response.raise_for_status()
        for task in tasks:
            task.cancel()


asyncio.run(main())
