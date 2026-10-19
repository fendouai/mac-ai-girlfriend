"""Run the isolated native MLX material generator with a bounded Metal cache."""
from pathlib import Path
import os
import runpy
import json
import shutil
import time
import hashlib
from PIL import Image
import mlx.core as mx

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'models/character3d-work'
PAINT=ROOT/'third_party/assetfurnace/hunyuan_mlx/paint'
source=ROOT/'data/avatars/generated/sweet-3d-front-v1.png'
mesh=WORK/'sweet-refined-shape.obj'
if not mesh.exists():raise RuntimeError('Refine and validate the hand surface before painting')
import trimesh
if not trimesh.load(mesh,force='mesh').is_watertight:
    raise RuntimeError('Refined geometry must pass its closed-surface check before painting')
# Preserve the photograph's aspect ratio in the square conditioning tensor.
# The source PNG itself remains unchanged.
im=Image.open(source).convert('RGBA')
box=im.getchannel('A').getbbox()
subject=im.crop(box)
size=max(im.size);target=int(size*.85)
subject.thumbnail((target,target),Image.Resampling.LANCZOS)
canvas=Image.new('RGB',(size,size),'white')
canvas.paste(subject,((size-subject.width)//2,(size-subject.height)//2),subject)
reference=WORK/'paint-conditioning-square.png';canvas.save(reference)
params=dict(PAINT_MESH=str(mesh),PAINT_IMG=str(reference),PAINT_SEED='0',
            PAINT_RES='512',PAINT_STEPS='15',PAINT_TEX='4096',PAINT_SR='1')
os.environ.update(params)
mx.set_cache_limit(512*1024**2)
mx.set_memory_limit(18*1024**3)
(PAINT/'outputs').mkdir(exist_ok=True)
os.chdir(PAINT)
start=time.time()
print('Starting custom material generation on Apple Metal',flush=True)
runpy.run_path(str(PAINT/'scripts/run_paint_pbr.py'),run_name='__main__')
shutil.copy2(PAINT/'outputs/textured_mesh_pbr.glb',WORK/'sweet-textured.glb')
record=dict(backend='Hunyuan3D-2.1-MLX-PBR',parameters=params,
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            geometry_sha256=hashlib.sha256(mesh.read_bytes()).hexdigest(),
            duration_seconds=time.time()-start,peak_gpu_bytes=mx.get_peak_memory(),
            license='Tencent Hunyuan Community License')
(WORK/'paint-provenance.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2),flush=True)
