"""Real simultaneous WS clients: independent history, output and disconnect cancellation."""
import asyncio
import base64
import json
import time

import websockets

URL = 'ws://127.0.0.1:7860/v1/realtime'


async def send(ws, text):
    await ws.send(json.dumps({'type': 'user.text', 'text': '请只回复：'+text}))


async def configure(ws):
    await ws.send(json.dumps({'type': 'session.update', 'session': {
        'avatar_transport': 'browser',
        'instructions': '你是中文测试助手。用户要求原样回复时，只输出指定原文，必须保留甲和乙等标记，不加解释。'}}))
    await completed(ws, '')


async def completed(ws, marker):
    audio = 0
    text = ''
    async with asyncio.timeout(30):
        async for raw in ws:
            event = json.loads(raw)
            if event['type'] == 'response.output_audio.delta':
                audio += len(base64.b64decode(event['delta']))
            if event['type'] == 'response.done':
                assert event['response']['status'] == 'completed', event
                text = event['response']['output'][0]['content'][0]['transcript']
                assert marker in text and audio > 3200, (marker, text, audio)
                return text


async def main():
    async with websockets.connect(URL) as first:
        await configure(first)
        await send(first, '甲页面工作正常。')
        # Opening and closing another tab must not reset the first reply.
        async with websockets.connect(URL) as other:
            await other.recv()
        one = await completed(first, '甲')
        async with websockets.connect(URL) as second:
            await configure(second)
            await send(first, '甲页面继续聊天。')
            await send(second, '乙页面也能聊天。')
            a, b = await asyncio.gather(completed(first, '甲'), completed(second, '乙'))
            # A disconnected generating tab must release synthesis promptly.
            await send(first, '今天的天气很好，我们可以一起出去散步，聊聊最近发生的有趣事情，然后找个安静的地方喝杯茶。')
            async with asyncio.timeout(10):
                async for raw in first:
                    event = json.loads(raw)
                    if event['type'] == 'response.progress' and event['stage'] == 'synthesizing':
                        break
            await asyncio.sleep(.5)
            await first.close()
            started = time.perf_counter()
            await send(second, '乙页面没有被打断。')
            after = await completed(second, '乙')
            elapsed = time.perf_counter()-started
            assert elapsed < 12, elapsed
    print(json.dumps(dict(passed=True, first_reply=one, simultaneous=[a,b],
                          surviving_reply=after, after_disconnect_seconds=elapsed), ensure_ascii=False), flush=True)


asyncio.run(main())
