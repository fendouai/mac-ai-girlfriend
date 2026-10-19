"""Compare the unchanged Qwen hidden states/KV cache with the unused head bypassed."""
import json
from pathlib import Path
import statistics
import time

import torch
from transformers import Qwen2ForCausalLM

torch.set_num_threads(4)
torch.manual_seed(17)
device = 'mps' if torch.backends.mps.is_available() else 'cpu'
model = Qwen2ForCausalLM.from_pretrained('models/CosyVoice2-0.5B/CosyVoice-BlankEN').eval().to(device)


def sync():
    if device == 'mps':
        torch.mps.synchronize()


@torch.inference_mode()
def run(legacy, steps=30):
    # Independent prefill and decode caches, same embeddings in both paths.
    xs = model.model.embed_tokens(torch.arange(128, device=device).reshape(1, -1))
    cache = None
    hidden = []
    sync(); started = time.perf_counter()
    for i in range(steps):
        mask = torch.ones((1, 128+i), dtype=torch.long, device=device)
        output = (model if legacy else model.model)(
            inputs_embeds=xs, attention_mask=mask, past_key_values=cache,
            use_cache=True, output_hidden_states=legacy, return_dict=True)
        last = output.hidden_states[-1] if legacy else output.last_hidden_state
        cache = output.past_key_values
        hidden.append(last[:, -1].cpu())
        xs = model.model.embed_tokens(torch.tensor([[1000+i]], device=device))
    sync()
    return torch.stack(hidden), time.perf_counter()-started


run(False, 3); run(True, 3)
legacy, old_time = run(True)
direct, new_time = run(False)
torch.testing.assert_close(legacy, direct, rtol=1e-5, atol=1e-5)
result = dict(passed=True, device=device, steps=30,
              max_hidden_difference=float((legacy-direct).abs().max()),
              legacy_seconds=old_time, optimized_seconds=new_time,
              speedup=old_time/new_time)
if device == 'mps':
    model.half()
    run(False)
    half, half_time = run(False)
    assert torch.isfinite(half).all()
    cosine = torch.nn.functional.cosine_similarity(direct.float(), half.float(), dim=-1).mean().item()
    assert cosine > .999, cosine
    result.update(fp16_seconds=half_time, fp16_hidden_cosine=cosine,
                  fp16_speedup=old_time/half_time)
Path('logs/speech-decoder-equivalence.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result), flush=True)
