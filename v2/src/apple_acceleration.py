"""Apple Core ML execution for the unchanged CosyVoice2 flow-estimator weights."""
import numpy as np
import torch


class CoreMLFlowEstimator(torch.nn.Module):
    def __init__(self, path, original):
        super().__init__()
        import coremltools as ct
        # Dynamic sequence lengths are supported by the GPU, not ANE compilation.
        self.network = ct.models.MLModel(path, compute_units=ct.ComputeUnit.CPU_AND_GPU)
        self.original = original

    def forward(self, x, mask, mu, t, spks, cond, streaming=False):
        if streaming or not 32 <= x.shape[-1] <= 2048:
            return self.original(x, mask, mu, t, spks, cond, streaming=streaming)
        tensors = dict(x=x, mask=mask, mu=mu, t=t, spks=spks, cond=cond)
        inputs = {name: value.detach().float().cpu().numpy() for name, value in tensors.items()}
        result = self.network.predict(inputs)['prediction']
        return torch.from_numpy(np.asarray(result, dtype=np.float32)).to(device=x.device, dtype=x.dtype)


class MLXSpeechDecoder:
    """Same CosyVoice Qwen weights and sampling, native Metal KV-cache decoding.

    Only the transformer and speech head move to MLX. Prompt extraction, speaker
    identity, Flow, HiFT, stop tokens and repetition-aware sampling stay unchanged.
    No quantization or conversion service is involved.
    """

    def __init__(self, speech_lm, dtype='float32'):
        import mlx.core as mx
        import mlx.nn as nn
        from mlx.utils import tree_flatten
        from mlx_lm.models.qwen2 import ModelArgs, Qwen2Model

        self.mx = mx
        source = speech_lm.llm.model
        args = ModelArgs.from_dict({**source.config.to_dict(), 'vocab_size': 1})
        self.network = Qwen2Model(args)
        weights = [(name, mx.array(value.detach().float().cpu().numpy()))
                   for name, value in source.model.state_dict().items()
                   if name != 'embed_tokens.weight' and 'rotary_emb.inv_freq' not in name]
        expected = {name for name, _ in tree_flatten(self.network.parameters())} - {'embed_tokens.weight'}
        if {name for name, _ in weights} != expected:
            raise ValueError('MLX speech decoder weight names do not match Qwen2')
        self.network.load_weights(weights, strict=False)
        self.head = nn.Linear(speech_lm.llm_output_size, speech_lm.speech_token_size+3)
        self.head.load_weights([(key, mx.array(value.detach().float().cpu().numpy()))
                                for key, value in speech_lm.llm_decoder.state_dict().items()])
        self.embedding = mx.array(speech_lm.speech_embedding.weight.detach().float().cpu().numpy())
        mx.eval(self.network.parameters(), self.head.parameters(), self.embedding)
        self.network.eval()
        self.head.eval()
        self.set_dtype(dtype)

    def set_dtype(self, dtype):
        if dtype not in ('float32', 'float16'):
            raise ValueError('MLX speech dtype must be float32 or float16')
        target = getattr(self.mx, dtype)
        self.network.set_dtype(target)
        self.head.set_dtype(target)
        self.embedding = self.embedding.astype(target)
        self.mx.eval(self.network.parameters(), self.head.parameters(), self.embedding)

    def new_cache(self):
        from mlx_lm.models.cache import KVCache
        return [KVCache() for _ in self.network.layers]

    def release_torch_decoder(self, speech_lm):
        # Keep text embeddings and the public encoder interface for bistream,
        # but do not retain a second 24-layer decoder in unified memory.
        core = speech_lm.llm.model.model
        core.layers = torch.nn.ModuleList()
        core.norm = torch.nn.Identity()
        speech_lm.llm.native_decoder = self
        import gc
        gc.collect()
        torch.mps.empty_cache()
        self.mx.set_cache_limit(256*1024*1024)
        self.mx.clear_cache()

    def forward_one_step(self, inputs, cache=None):
        cache = self.new_cache() if cache is None else cache
        embeddings = self.mx.array(inputs.detach().float().cpu().numpy()).astype(self.embedding.dtype)
        hidden = self.network(None, cache=cache, input_embeddings=embeddings)
        self.mx.eval(hidden)
        result = torch.from_numpy(np.array(hidden.astype(self.mx.float32), copy=True))
        return result.to(device=inputs.device, dtype=inputs.dtype), cache

    def logits(self, embeddings, cache):
        embeddings = embeddings.astype(self.embedding.dtype)
        hidden = self.network(None, cache=cache, input_embeddings=embeddings)
        logits = self.head(hidden[:, -1])
        self.mx.eval(logits)
        return np.array(logits.astype(self.mx.float32), copy=True)

    def inference(self, speech_lm, lm_input, sampling, min_len, max_len):
        mx = self.mx
        cache = self.new_cache()
        inputs = mx.array(lm_input.detach().float().cpu().numpy())
        out_tokens = []
        for i in range(max_len):
            logp = torch.from_numpy(self.logits(inputs, cache)).log_softmax(dim=-1)
            token = speech_lm.sampling_ids(logp.squeeze(0), out_tokens, sampling, ignore_eos=i < min_len)
            if token in speech_lm.stop_token_ids:
                break
            yield token
            out_tokens.append(token)
            inputs = self.embedding[token].reshape(1, 1, -1)
