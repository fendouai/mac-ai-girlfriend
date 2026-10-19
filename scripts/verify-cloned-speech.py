"""Check generated speech intelligibility with the unchanged local STT model."""
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sys
import wave

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from stt import build_stt

cfg = yaml.safe_load((ROOT/'config.mac.yaml').read_text())
stt = build_stt(cfg)
records = json.loads((ROOT/'logs/fast-face-e2e-results.json').read_text())['replies']
results = []
normalize = lambda value: re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', value).lower()
for record in records:
    if record['label'] == 'welcome':
        continue
    with wave.open(str(ROOT/'logs'/('optimized-'+record['label']+'.wav')),'rb') as audio:
        samples = np.frombuffer(audio.readframes(audio.getnframes()),dtype='<i2').astype(np.float32)/32768
    recognized = stt.transcribe(samples)
    score = SequenceMatcher(None, normalize(record['transcript']), normalize(recognized)).ratio()
    clipping = float(np.mean(abs(samples) >= .999))
    assert score > .85 and clipping < .01, (recognized, score, clipping)
    results.append(dict(label=record['label'], transcript=recognized,
                        character_similarity=score, clipping_fraction=clipping))
(ROOT/'logs/cloned-speech-intelligibility.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(passed=True, checks=results),ensure_ascii=False),flush=True)
