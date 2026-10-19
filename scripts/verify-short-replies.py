"""Real LLM + cloned TTS: short answers, a complete short joke and continuation."""
import asyncio
import base64
import json
from pathlib import Path
import re
import time

import websockets


async def receive(ws, label, started):
    text='';audio=0;first=None
    async with asyncio.timeout(60):
        async for raw in ws:
            event=json.loads(raw)
            if event['type']=='error':
                raise RuntimeError(event)
            if event['type']=='response.output_audio_transcript.delta':
                text+=event.get('delta','')
            if event['type']=='response.output_audio.delta':
                audio+=len(base64.b64decode(event['delta']))
                first=first or time.perf_counter()
            if event['type']=='response.done':
                assert event['response']['status']=='completed',event
                assert text and len(text)<=40 and len(re.findall('[。！？!?]+',text))<=2,(label,text)
                assert first and audio>3200,(label,audio)
                result=dict(label=label,text=text,chars=len(text),first_audio_seconds=first-started,
                            audio_seconds=audio/32000)
                print(json.dumps(result,ensure_ascii=False),flush=True)
                return result


async def main():
    results=[]
    async with websockets.connect('ws://127.0.0.1:7860/v1/realtime') as ws:
        started=time.perf_counter()
        # Represents an existing browser with an old verbose persona saved.
        await ws.send(json.dumps({'type':'session.update','session':{
            'avatar_transport':'browser','instructions':'你叫阿汐，温柔亲近。以前的习惯是详细回答、多安慰几句。'}}))
        results.append(await receive(ws,'welcome',started))
        for label,prompt in [('comfort','今天加班有点累。'),('joke','给我讲个笑话。'),
                             ('explanation','怎么安排周末休息？请详细讲讲。'),('continue','继续。')]:
            started=time.perf_counter()
            await ws.send(json.dumps({'type':'user.text','text':prompt}))
            results.append(await receive(ws,label,started))
    assert results[-1]['text']!=results[-2]['text'],'Continuation repeated the same answer'
    Path('logs/short-replies-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(passed=True,replies=len(results))),flush=True)


asyncio.run(main())
