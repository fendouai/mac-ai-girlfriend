"""Generate an actual humanoid surface from the GPT source photo on Apple MLX.

Run with third_party/assetfurnace/hunyuan_mlx/shape/.venv/bin/python.
Keeps the dense surface plus a smaller rigging/painting mesh and measured provenance.
"""
from pathlib import Path
import hashlib
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / 'third_party/assetfurnace'
sys.path.insert(0, str(LAB / 'hunyuan_mlx/shape'))
import mlx.core as mx
import fast_simplification
import trimesh
from hy3dmlx.pipeline import Hunyuan3DShapePipeline

image = ROOT / 'data/avatars/generated/sweet-3d-front-v1.png'
output = ROOT / 'models/character3d-work'
output.mkdir(parents=True, exist_ok=True)
params = dict(num_inference_steps=30, guidance_scale=5.0, octree_resolution=1024,
              seed=42, octree_decode=True, compile_dit=True)
start = time.time()
print('Generating custom sweet character on', mx.device_info()['device_name'], flush=True)
pipe = Hunyuan3DShapePipeline.from_pretrained(
    str(LAB / 'hunyuan_mlx/shape/weights/Hunyuan3D-2/hunyuan3d-dit-v2-0'),
    dtype=mx.float16, quantize=8)
mesh = pipe.generate(str(image), **params)
mesh.export(output / 'sweet-dense.glb')
stats = dict(vertices=len(mesh.vertices), faces=len(mesh.faces), bounds=mesh.bounds.tolist(),
             watertight=bool(mesh.is_watertight), components=len(mesh.split(only_watertight=False)))
if len(mesh.faces) > 120000:
    vertices, faces = fast_simplification.simplify(mesh.vertices, mesh.faces, target_count=120000)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
parts = mesh.split(only_watertight=False)
all_faces = len(mesh.faces)
mesh = max(parts, key=lambda part: len(part.faces))
mesh.export(output / 'sweet-shape.obj')
mesh.export(output / 'sweet-shape.glb')
record = dict(backend='Hunyuan3D-2.0-MLX', quantize=8, source=str(image.relative_to(ROOT)),
              source_sha256=hashlib.sha256(image.read_bytes()).hexdigest(), parameters=params,
              dense=stats, faces=len(mesh.faces), vertices=len(mesh.vertices),
              cleanup=dict(discarded_small_components=len(parts)-1, discarded_faces=all_faces-len(mesh.faces)),
              duration_seconds=time.time()-start, peak_gpu_bytes=mx.get_peak_memory(),
              license='Tencent Hunyuan Community License')
(output / 'shape-provenance.json').write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(record, indent=2), flush=True)
