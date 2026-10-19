"""Exercise typed input through the real local LLM and cloned speech engine."""
import asyncio
import base64
import json
import time

import numpy as np
import websockets


async def main():
    async with websockets.connect('ws://127.0.0.1:7860/v1/realtime') as ws:
        await ws.send(json.dumps({'type': 'session.update', 'session': {'avatar_transport': 'browser'}}))
        # Drain the real welcome response before issuing the controlled test turn.
        async with asyncio.timeout(120):
            async for raw in ws:
                if json.loads(raw)['type'] == 'response.done':
                    break
        text = '请用一句简短的中文问候我，然后挥挥手。'
        started = time.perf_counter()
        await ws.send(json.dumps({'type': 'user.text', 'text': text}))
        transcript = ''
        pcm = bytearray()
        acknowledged = interrupted = False
        first_audio = None
        async with asyncio.timeout(120):
            async for raw in ws:
                event = json.loads(raw)
                kind = event['type']
                if kind == 'error':
                    raise AssertionError(event)
                if kind == 'input_audio_buffer.speech_started':
                    interrupted = True
                if kind == 'conversation.item.input_text.completed':
                    assert event['transcript'] == text
                    acknowledged = True
                if kind == 'response.output_audio_transcript.delta':
                    transcript += event.get('delta', '')
                if kind == 'response.output_audio.delta':
                    first_audio = first_audio or time.perf_counter()
                    pcm.extend(base64.b64decode(event['delta']))
                if kind == 'response.done':
                    break
        samples = np.frombuffer(pcm, dtype='<i2').astype(float)
        assert acknowledged and interrupted, 'Missing input acknowledgement or playback interruption'
        assert transcript.strip() and len(samples) > 2400, 'Missing actual LLM text or cloned speech'
        rms = float(np.sqrt(np.mean(samples ** 2)))
        assert rms > 100, 'Speech output is silent'
        print(json.dumps({'passed': True, 'reply': transcript, 'audio_bytes': len(pcm),
                          'rms': rms, 'first_audio_seconds': first_audio - started}, ensure_ascii=False), flush=True)


asyncio.run(main())
