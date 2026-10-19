"""Cancel during real Core ML Flow, then check a new short reply isn't queued."""
import asyncio
import json
from pathlib import Path
import time

import websockets


async def main():
    log = Path('logs/mac-optimized-final-20261019.log')
    async with websockets.connect('ws://127.0.0.1:7860/v1/realtime') as ws:
        await ws.send(json.dumps({'type':'session.update','session':{
            'avatar_transport':'browser','instructions':'你是中文测试助手。只输出用户指定的原文，不加解释。'}}))
        async with asyncio.timeout(30):
            async for raw in ws:
                if json.loads(raw)['type']=='response.done':
                    break
        position = len(log.read_bytes())
        await ws.send(json.dumps({'type':'user.text','text':'请原样回复：今天的天气很好，我们可以一起出去散步，聊聊最近发生的有趣事情，然后找个安静的地方喝杯茶。'}))
        # Token completion is logged immediately before the acoustic Flow stage.
        async with asyncio.timeout(20):
            while b'cosy speech_tokens=' not in log.read_bytes()[position:]:
                await asyncio.sleep(.03)
        await asyncio.sleep(.15)
        started = time.perf_counter()
        await ws.send(json.dumps({'type':'response.cancel'}))
        await ws.send(json.dumps({'type':'user.text','text':'请只回复：好的。'}))
        cancelled = None
        first = None
        async with asyncio.timeout(20):
            async for raw in ws:
                event = json.loads(raw)
                if event['type']=='response.done' and event['response']['status']=='cancelled':
                    cancelled = time.perf_counter()-started
                if event['type']=='response.output_audio.delta':
                    first = first or time.perf_counter()-started
                if event['type']=='response.done' and event['response']['status']=='completed':
                    break
        assert cancelled is not None and cancelled < 1.5, cancelled
        assert first is not None and first < 7, first
        assert 'Traceback' not in log.read_bytes()[position:].decode()
        result = dict(passed=True, flow_cancel_to_done_seconds=cancelled, replacement_first_audio_seconds=first)
        Path('logs/flow-cancellation-results.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result),flush=True)


asyncio.run(main())
