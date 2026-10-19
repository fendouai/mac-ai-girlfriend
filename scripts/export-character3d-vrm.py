"""Package the actual custom GLB skin and facial morphs as VRM 1.0 for the web driver."""
from pathlib import Path
import hashlib
import json
import struct
import argparse

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'models/character3d-work'
parser=argparse.ArgumentParser()
parser.add_argument('--source',type=Path,default=WORK/'sweet-final-rig.glb')
args=parser.parse_args()
source=args.source
mapping=json.loads((WORK/'final-rig-map.json').read_text())
data=source.read_bytes()
magic,version,total=struct.unpack_from('<III',data)
if magic!=0x46546c67 or version!=2 or total!=len(data):raise RuntimeError('Invalid assembled GLB')
json_length,json_type=struct.unpack_from('<II',data,12)
if json_type!=0x4e4f534a:raise RuntimeError('GLB has no JSON chunk')
document=json.loads(data[20:20+json_length])
rest=data[20+json_length:]
nodes={node.get('name'):index for index,node in enumerate(document['nodes'])}
human={name:{'node':nodes[bone]} for name,bone in mapping['humanoid'].items()}
face_node=nodes[mapping['face_object']]
mesh=document['meshes'][document['nodes'][face_node]['mesh']]
targets=mesh.get('extras',{}).get('targetNames',[])
expressions={name:dict(isBinary=False,morphTargetBinds=[dict(node=face_node,index=index,weight=1.0)])
             for index,name in enumerate(targets)}
for required in ['aa','oh','ih','blink','happy']:
    if required not in expressions:raise RuntimeError(f'Missing actual facial morph: {required}')
document.setdefault('extensions',{})['VRMC_vrm']={
    'specVersion':'1.0',
    'meta':{'name':'Sweet Asian · custom GPT image character','version':'1.0',
            'authors':['Local custom avatar project'],
            'licenseUrl':'https://vrm.dev/licenses/1.0/'},
    'humanoid':{'humanBones':human},
    'expressions':{'preset':expressions},
    'firstPerson':{'meshAnnotations':[{'node':face_node,'type':'both'}]},
}
used=document.setdefault('extensionsUsed',[])
if 'VRMC_vrm' not in used:used.append('VRMC_vrm')
encoded=json.dumps(document,separators=(',',':'),ensure_ascii=False).encode()
encoded+=b' '*((-len(encoded))%4)
output=struct.pack('<III',magic,version,20+len(encoded)+len(rest))+struct.pack('<II',len(encoded),json_type)+encoded+rest
destination=ROOT/'web/assets/models/sweet-realistic.vrm';destination.write_bytes(output)
stages={name:json.loads((WORK/file).read_text()) for name,file in [
    ('geometry','shape-provenance.json'),('hands','hands-provenance.json'),
    ('materials','paint-provenance.json'),('skeleton','rig-provenance.json'),
    ('face','face-rig-provenance.json')]}
stages['assembly']=mapping
if source.name=='sweet-polished.glb':stages['polish']=json.loads((WORK/'polish-provenance.json').read_text())
provenance=dict(file=destination.name,sha256=hashlib.sha256(output).hexdigest(),bytes=len(output),
    character='Fictional adult sweet Asian woman generated with the built-in GPT image tool',
    reference_images=['data/avatars/generated/sweet-clean-v1.png','data/avatars/generated/sweet-3d-front-v1.png'],
    rear_reference='data/avatars/generated/sweet-3d-back-v1.png (visual QA reference)',
    humanoid_bones=len(human),facial_morphs=targets,stages=stages,
    attribution=[dict(component='MakeHuman anatomical hand template',license='CC0',
                      source='https://github.com/makehumancommunity/makehuman'),
                 dict(component='MediaPipe canonical face topology',license='Apache-2.0',
                      source='https://github.com/google-ai-edge/mediapipe'),
                 dict(component='AssetFurnace Apple Silicon pipeline',license='Apache-2.0',
                      source='https://github.com/Bingeljell/image-to-3dlab')],
    limitations='Audio-energy/frequency driven visemes; no claim of Mandarin phoneme-level alignment. Hair is a generated mesh, without strand-level hair simulation. Sad/relaxed are reserved zero morphs; blink, happy and three mouth shapes have actual deformation.')
(destination.parent/'sweet-realistic.source.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(file=str(destination),bytes=len(output),humanoid_bones=len(human),facial_morphs=targets),ensure_ascii=False,indent=2))
