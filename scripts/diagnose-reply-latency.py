"""Measure real local reply latency without microphone or an extra avatar session."""
import asyncio
import base64
import json
import sys
from pathlib import Path
import time
import wave

import httpx
import numpy as np
import websockets


async def receive(ws, label, started):
    first_audio = None
    pcm = bytearray()
    transcript = ''
    async with asyncio.timeout(150):
        async for raw in ws:
            event = json.loads(raw)
            kind = event['type']
            if kind == 'error':
                raise RuntimeError(event)
            if kind == 'response.output_audio_transcript.delta':
                transcript += event.get('delta', '')
            if kind == 'response.output_audio.delta':
                first_audio = first_audio or time.perf_counter()
                pcm.extend(base64.b64decode(event['delta']))
            if kind == 'response.done':
                if event['response'].get('status') == 'cancelled':
                    continue
                samples = np.frombuffer(pcm, dtype='<i2').astype(float)
                assert first_audio and len(samples) > 2400, event
                rms = float(np.sqrt(np.mean(samples**2)))
                assert rms > 100, 'Silent speech'
                result = dict(label=label, first_audio_seconds=first_audio-started,
                              audio_seconds=len(pcm)/32000, chars=len(transcript),
                              transcript=transcript, rms=rms)
                with wave.open('logs/optimized-'+label+'.wav', 'wb') as audio:
                    audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                    audio.writeframes(pcm)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                return result


async def main():
    async with httpx.AsyncClient() as client:
        for _ in range(90):
            try:
                health = (await client.get('http://127.0.0.1:7860/api/health')).json()
                if health.get('startup_error'):
                    raise RuntimeError(health)
                if health.get('ok'):
                    break
            except httpx.TransportError:
                pass
            await asyncio.sleep(1)
        else:
            raise RuntimeError('Engines did not become ready')
    results = []
    async with websockets.connect('ws://127.0.0.1:7860/v1/realtime', max_size=8*1024*1024) as ws:
        started = time.perf_counter()
        await ws.send(json.dumps({'type': 'session.update', 'session': {
            'avatar_transport': 'browser',
            'instructions': '你是中文语音助手。用户要求原样回复时，只输出指定原文，不加解释。'}}))
        results.append(await receive(ws, 'welcome', started))
        if '--interrupt-only' in sys.argv:
            await ws.send(json.dumps({'type': 'user.text', 'text': '请原样回复：今天的天气很好，我们可以一起出去散步，聊聊最近发生的有趣事情，然后找个安静的地方喝杯茶。'}))
            # Start the replacement after the old reply has entered synthesis.
            await asyncio.sleep(4)
            started = time.perf_counter()
            await ws.send(json.dumps({'type': 'user.text', 'text': '请只回复：好的。'}))
            results.append(await receive(ws, 'replacement_after_interrupt', started))
            Path('logs/reply-latency-interrupt-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n')
            return
        for label, text in [('short', '你好呀，我在这里陪着你。'),
                            ('long', '今天的天气很好，我们可以一起出去散步，聊聊最近发生的有趣事情，然后找个安静的地方喝杯茶。')]:
            started = time.perf_counter()
            await ws.send(json.dumps({'type': 'user.text', 'text': '请原样回复：'+text}))
            results.append(await receive(ws, label, started))
    Path('logs/reply-latency-results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n')


asyncio.run(main())
