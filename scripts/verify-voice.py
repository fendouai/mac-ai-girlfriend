import asyncio,json,base64,os
import numpy as np
import websockets
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
import os
os.chdir(ROOT)
sys.path.insert(0,str(ROOT/'src'))
from tts import MacOSSayTTS
from audio_utils import wav_to_pcm16_bytes

async def receive_reply(ws):
    got_audio=False; recognized=None
    async with asyncio.timeout(120):
        async for msg in ws:
            e=json.loads(msg);t=e['type']
            if t=='conversation.item.input_audio_transcription.completed':
                recognized=e.get('transcript');print('STT:',recognized,flush=True)
            if t=='response.output_audio_transcript.delta':print('LLM:',e.get('delta'),flush=True)
            if t=='response.output_audio.delta':
                pcm=base64.b64decode(e['delta']);assert len(pcm)>3200
                got_audio=True;print('TTS PCM:',len(pcm),'bytes',flush=True)
            if t=='response.done':
                assert got_audio,'Missing audio';return recognized

async def main():
    chunks=[];MacOSSayTTS().synthesize('你好呀，请问你叫什么名字？',chunks.append)
    async with websockets.connect('ws://127.0.0.1:7860/v1/realtime') as ws:
        await ws.send(json.dumps({'type':'session.update','session':{'avatar_transport':os.environ.get('HEX_VERIFY_TRANSPORT','webrtc')}}))
        await receive_reply(ws)
        pcm=b'\0'*32000+wav_to_pcm16_bytes(chunks[0])+b'\0'*64000
        for i in range(0,len(pcm),4096):
            await ws.send(json.dumps({'type':'input_audio_buffer.append','audio':base64.b64encode(pcm[i:i+4096]).decode()}))
            await asyncio.sleep(.02)
        text=await receive_reply(ws);assert text,'Missing recognized text'
        print('PASS: speech → VAD → configured STT → local LLM → configured TTS → WebSocket audio',flush=True)
asyncio.run(main())
