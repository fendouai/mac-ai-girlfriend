"""Bind the generated textured body with pinned local SkinTokens, then clean weights."""
from pathlib import Path
import os
import json
import time
import hashlib
import subprocess
import shutil

ROOT=Path(__file__).resolve().parents[1]
LAB=ROOT/'third_party/assetfurnace'
SKIN=LAB/'vendor/SkinTokens'
WORK=ROOT/'models/character3d-work'
source=WORK/'sweet-textured.glb'
record=json.loads((WORK/'paint-provenance.json').read_text())
if not source.exists():raise RuntimeError('Material generation has not finished')
geometry=WORK/'sweet-refined-shape.obj'
if hashlib.sha256(geometry.read_bytes()).hexdigest()!=record['geometry_sha256']:
    raise RuntimeError('Paint was generated from an older body surface')
env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
     'PYTORCH_ENABLE_MPS_FALLBACK':'1','TOKENIZERS_PARALLELISM':'false',
     'GRADIO_ANALYTICS_ENABLED':'False','PYTHONUNBUFFERED':'1','OMP_NUM_THREADS':'4'}
python=SKIN/'.venv/bin/python'
output=WORK/'sweet-rigged.glb'
start=time.time()
server=SKIN/'src/server/bpy_server.py'
server_code=server.read_text()
if "host='0.0.0.0'" in server_code:
    server.write_text(server_code.replace("host='0.0.0.0'", "host='127.0.0.1'"))
subprocess.run([str(python),'demo.py','--input',str(source),'--output',str(output),
                '--use_transfer'],cwd=SKIN,env=env,check=True)
if not output.exists():raise RuntimeError('SkinTokens did not export its rig')
shutil.copy2(output,WORK/'sweet-rigged-raw.glb')
subprocess.run([str(python),str(LAB/'scripts/clean_skin_weights.py'),
                '--in',str(output),'--out',str(output)],cwd=LAB,env=env,check=True)
provenance=dict(backend='SkinTokens on PyTorch MPS',
    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
    duration_seconds=time.time()-start,license='MIT',
    repository='https://github.com/VAST-AI-Research/SkinTokens',
    code_commit='273b691d35989d71cd17ff2895fdc735097b92d1',
    weight_revision='79736cad0fd84de384d5eede659b4ebd24effe33')
(WORK/'rig-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
print(json.dumps(provenance,indent=2),flush=True)
