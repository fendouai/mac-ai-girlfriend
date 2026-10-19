"""Teacher-forced speech-logit equivalence, using actual cloned-voice weights."""
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from tts import build_tts

torch.set_num_threads(4)
cfg = yaml.safe_load((ROOT/'config.mac.yaml').read_text())
cfg['tts']['speech_backend'] = 'mlx'
cfg['tts']['speech_dtype'] = 'float32'
cfg['tts']['speech_release_torch'] = False
tts = build_tts(cfg)
lm = tts.model.model.llm
native = lm.native_decoder


@torch.inference_mode()
def prefix():
    prompt = tts._cached_prompt_input()
    front = tts.model.frontend
    target, _ = front._extract_text_token('今天的天气很好，我们可以一起出去散步。')
    text = torch.cat([prompt['prompt_text'], target], dim=1).to('mps')
    return torch.cat([lm.llm_embedding.weight[lm.sos].reshape(1,1,-1),
                      lm.llm.model.model.embed_tokens(text),
                      lm.llm_embedding.weight[lm.task_id].reshape(1,1,-1),
                      lm.speech_embedding(prompt['llm_prompt_speech_token'].to('mps'))], dim=1)


@torch.inference_mode()
def run_torch(inputs):
    cache = None
    out = []
    started = time.perf_counter()
    offset = 0
    for i in range(30):
        offset += inputs.shape[1]
        mask = torch.ones((1, 1, offset), dtype=torch.bool, device='mps')
        hidden, cache = lm.llm.forward_one_step(inputs, mask, cache)
        out.append(lm.llm_decoder(hidden[:,-1]).cpu().numpy())
        inputs = lm.speech_embedding.weight[100+i].reshape(1,1,-1)
    return np.stack(out), time.perf_counter()-started


def run_mlx(inputs):
    inputs = native.mx.array(inputs.detach().float().cpu().numpy())
    cache = native.new_cache()
    out = []
    started = time.perf_counter()
    for i in range(30):
        out.append(native.logits(inputs, cache))
        inputs = native.embedding[100+i].reshape(1,1,-1)
    return np.stack(out), time.perf_counter()-started


inputs = prefix()
run_mlx(inputs); run_torch(inputs)
expected, torch_seconds = run_torch(inputs)
actual, mlx_seconds = run_mlx(inputs)
np.testing.assert_allclose(actual, expected, rtol=.003, atol=.003)
agreement = float((actual.argmax(-1)==expected.argmax(-1)).mean())
assert agreement == 1, agreement
result = dict(passed=True, dtype='float32', steps=30,
              max_logit_difference=float(abs(actual-expected).max()),
              greedy_token_agreement=agreement, torch_seconds=torch_seconds,
              mlx_seconds=mlx_seconds, speedup=torch_seconds/mlx_seconds)
native.set_dtype('float16')
run_mlx(inputs)
half, half_seconds = run_mlx(inputs)
cosine = float(np.mean(np.sum(expected*half, axis=-1) / (np.linalg.norm(expected, axis=-1)*np.linalg.norm(half, axis=-1))))
half_agreement = float((half.argmax(-1)==expected.argmax(-1)).mean())
assert np.isfinite(half).all() and cosine > .999 and half_agreement >= .96, (cosine, half_agreement, float(np.max(abs(half-expected))))
result.update(fp16_seconds=half_seconds, fp16_logit_cosine=cosine,
              fp16_greedy_agreement=half_agreement, fp16_speedup=torch_seconds/half_seconds)
native.release_torch_decoder(lm)
released, _ = run_torch(inputs)
assert np.isfinite(released).all()
assert float((released.argmax(-1)==expected.argmax(-1)).mean()) >= .96
result.update(torch_decoder_layers=len(lm.llm.model.model.layers),
              mlx_active_bytes=native.mx.get_active_memory(),
              mlx_cache_bytes=native.mx.get_cache_memory())
(ROOT/'logs/native-speech-decoder-equivalence.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result), flush=True)
