"""Offline noise sensitivity of the current VAD; never records the microphone."""
import json
from pathlib import Path
import sys
import wave

import numpy as np
import torch
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from vad import SileroVAD, EndpointDetector

torch.set_num_threads(2)
cfg = yaml.safe_load((ROOT/'config.mac.yaml').read_text())['vad']
sr = 16000
rng = np.random.default_rng(19)


def load(name):
    with wave.open(str(ROOT/'logs'/name),'rb') as audio:
        assert audio.getframerate()==sr
        return np.frombuffer(audio.readframes(audio.getnframes()),dtype='<i2').astype(np.float32)/32768


def level(signal, db):
    return signal*(10**(db/20))/max(float(np.sqrt(np.mean(signal**2))),1e-8)


short = load('optimized-short.wav')
background = load('optimized-long.wav')
n = sr*10
t = np.arange(n)/sr
fan = rng.normal(size=n).astype(np.float32)
fan = np.convolve(fan, np.ones(9)/9, mode='same').astype(np.float32)+.4*np.sin(2*np.pi*120*t)
fan = level(fan,-35)
clicks = np.zeros(n,dtype=np.float32)
for start in np.arange(.3,8,.25):
    i=int(start*sr)
    clicks[i:i+160] = rng.normal(size=160)*np.hanning(160)*.12
voice = np.zeros(n,dtype=np.float32)
voice[sr:sr+len(short)] = short
bg = np.zeros(n,dtype=np.float32)
bg[2*sr:8*sr] = level(np.resize(background,6*sr),-38)
cases = {'silence':np.zeros(n,dtype=np.float32),
         'fan_only_minus35db':fan, 'clicks_only':clicks,
         'background_speech_only_minus38db':bg,
         'speech_clean':voice, 'speech_with_fan':voice+fan,
         'speech_with_clicks':voice+clicks, 'speech_then_background_speech':voice+bg}
vad = SileroVAD(device='cpu',sample_rate=sr)
results = []
for name, signal in cases.items():
    vad.model.reset_states()
    detector = EndpointDetector(threshold=cfg.get('threshold',.5),
        min_speech_ms=cfg['min_speech_ms'],min_silence_ms=cfg['min_silence_ms'],sr=sr)
    events=[]; probs=[]
    for i in range(0,len(signal)-511,512):
        frame = np.ascontiguousarray(signal[i:i+512],dtype=np.float32)
        prob = vad.speech_prob(frame)
        probs.append(prob)
        for kind,payload in detector.feed(prob,frame):
            events.append(dict(kind=kind,seconds=round((i+512)/sr,3)))
    result = dict(case=name,input_rms_db=float(20*np.log10(max(float(np.sqrt(np.mean(signal**2))),1e-9))),
                  max_speech_probability=max(probs),events=events)
    results.append(result)
    print(json.dumps(result),flush=True)
(ROOT/'logs/noise-vad-results.json').write_text(json.dumps(results,indent=2)+'\n')
