"""Fetch the pinned MLX shape/paint and portable SkinTokens checkpoints.

Isolated from the voice environment. Resumable range downloads are SHA-256 verified
against Hugging Face's LFS object IDs before any checkpoint is loaded.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib
import json
import time
import requests

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / 'third_party/assetfurnace'
PARTS = ROOT / 'models/.character3d-parts'
PARTS.mkdir(parents=True, exist_ok=True)
SOURCES = [
    ('tencent/Hunyuan3D-2', '9cd649ba6913f7a852e3286bad86bfa9a2d83dcf',
     LAB / 'hunyuan_mlx/shape/weights/Hunyuan3D-2',
     ['hunyuan3d-dit-v2-0/config.yaml', 'hunyuan3d-dit-v2-0/model.fp16.safetensors']),
    ('zimengxiong/hunyuan3d-mlx-paint-large', 'b56e8b86b4d1e62b0bb3bbef7e2070d6ec22620e',
     LAB / 'hunyuan_mlx/paint/weights/hunyuan3d-paintpbr-v2-1',
     ['unet/config.json', 'unet/diffusion_pytorch_model.safetensors',
      'vae/config.json', 'vae/diffusion_pytorch_model.safetensors',
      'dinov2/config.json', 'dinov2/model.safetensors', 'dinov2/preprocessor_config.json',
      'scheduler/scheduler_config.json', 'realesrgan/rrdbnet_mlx.safetensors']),
    ('VAST-AI/SkinTokens', '79736cad0fd84de384d5eede659b4ebd24effe33',
     LAB / 'vendor/SkinTokens',
     ['experiments/articulation_xl_quantization_256_token_4/grpo_1400.ckpt',
      'experiments/skin_vae_2_10_32768/last.ckpt']),
    ('Qwen/Qwen3-0.6B', 'c1899de289a04d12100db370d81485cdf75e47ca',
     LAB / 'vendor/SkinTokens/models/Qwen3-0.6B',
     ['config.json', 'tokenizer.json', 'tokenizer_config.json', 'merges.txt', 'vocab.json']),
]
CHUNK = 8 * 1024 * 1024


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(CHUNK), b''):
            h.update(chunk)
    return h.hexdigest()


def request(url, **kwargs):
    last = None
    for attempt in range(8):
        try:
            endpoint = url if attempt % 2 == 0 else url.replace('hf-mirror.com', 'huggingface.co')
            r = requests.get(endpoint, timeout=(15, 75), **kwargs)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            last = exc
            time.sleep(min(2 ** attempt, 8))
    raise last


def main():
    records, jobs = [], []
    for repo, rev, base, files in SOURCES:
        entries = request(f'https://hf-mirror.com/api/models/{repo}/tree/{rev}?recursive=true').json()
        by_path = {e['path']: e for e in entries if e['type'] == 'file'}
        for filename in files:
            e = by_path[filename]
            item = dict(repo=repo, revision=rev, path=filename, size=e['size'],
                        sha256=e.get('lfs', {}).get('oid'), target=str(base / filename))
            records.append(item)
            target = Path(item['target'])
            if target.exists() and target.stat().st_size == item['size']:
                if not item['sha256'] or digest(target) == item['sha256']:
                    continue
            key = hashlib.sha256(f'{repo}/{rev}/{filename}'.encode()).hexdigest()[:24]
            item['part_key'] = key
            for start in range(0, e['size'], CHUNK):
                jobs.append((item, start, min(e['size'], start + CHUNK) - 1))
    print(f'Pinned character modeling weights: {sum(r["size"] for r in records)/1e9:.2f} GB, {len(jobs)} parts', flush=True)

    def fetch(job):
        item, start, end = job
        part = PARTS / f'{item["part_key"]}-{start}'
        if part.exists() and part.stat().st_size == end - start + 1:
            return
        url = f'https://hf-mirror.com/{item["repo"]}/resolve/{item["revision"]}/{item["path"]}'
        if item['repo'] == 'tencent/Hunyuan3D-2':
            # Tencent's own ModelScope mirror is faster locally; the pinned HF
            # SHA-256 below still decides whether these bytes may be used.
            url = ('https://modelscope.cn/api/v1/models/Tencent-Hunyuan/Hunyuan3D-2/repo'
                   f'?Revision=master&FilePath={item["path"]}')
        r = request(url, params={'hex3dpart': start}, headers={'Range': f'bytes={start}-{end}'})
        if len(r.content) != end - start + 1:
            raise RuntimeError(f'Incorrect byte range: {item["path"]}:{start}')
        tmp = part.with_suffix('.partial')
        tmp.write_bytes(r.content)
        tmp.replace(part)

    def assemble(item):
        target = Path(item['target'])
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + '.partial')
        with tmp.open('wb') as f:
            for start in range(0, item['size'], CHUNK):
                f.write((PARTS / f'{item["part_key"]}-{start}').read_bytes())
        if tmp.stat().st_size != item['size'] or (item['sha256'] and digest(tmp) != item['sha256']):
            raise RuntimeError(f'Checkpoint checksum mismatch: {target}')
        tmp.replace(target)
        print(f'Verified {item["repo"]}/{item["path"]}', flush=True)
    errors = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        pending = {pool.submit(fetch, job): job[0] for job in jobs}
        remaining = {id(r): (r['size'] + CHUNK - 1) // CHUNK for r in records if 'part_key' in r}
        for i, future in enumerate(as_completed(pending), 1):
            item = pending[future]
            try:
                future.result()
            except Exception as error:
                errors.append((item['path'], str(error)))
                print(f'Download error (cached parts kept): {item["path"]}: {type(error).__name__}',flush=True)
                continue
            remaining[id(item)] -= 1
            if remaining[id(item)] == 0:
                assemble(item)
            if i % 25 == 0 or i == len(jobs):
                print(f'Completed {i}/{len(jobs)} parts', flush=True)
    if errors:
        raise RuntimeError(f'{len(errors)} ranges failed; re-run to resume. First: {errors[0]}')
    (ROOT / 'models/character3d-sources.json').write_text(json.dumps(records, indent=2) + '\n')


if __name__ == '__main__':
    main()
