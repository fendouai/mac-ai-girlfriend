"""Export local Kimodo full-body motion samples in standard humanoid world axes."""
from pathlib import Path
import runpy
import json
import hashlib
import numpy as np
from scipy.spatial.transform import Rotation

ROOT=Path(__file__).resolve().parents[1]
LAB=ROOT/'third_party/assetfurnace'
module=runpy.run_path(str(LAB/'scripts/kimodo_retarget.py'))
mapping=dict(hips='Hips',spine='Spine1',chest='Spine2',upperChest='Chest',neck='Neck2',head='Head')
for side in ['left','right']:
    title=side.title()
    for bone,soma in [('Shoulder','Shoulder'),('UpperArm','Arm'),('LowerArm','ForeArm'),('Hand','Hand'),
                       ('UpperLeg','Leg'),('LowerLeg','Shin'),('Foot','Foot'),('Toes','ToeBase')]:
        mapping[side+bone]=title+soma
    for bone,soma in [('Metacarpal',1),('Proximal',2),('Distal',3)]:
        mapping[side+'Thumb'+bone]=title+'HandThumb'+str(soma)
    for finger in ['Index','Middle','Ring','Little']:
        for bone,soma in [('Proximal',2),('Intermediate',3),('Distal',4)]:
            mapping[side+finger+bone]=title+'Hand'+('Pinky' if finger=='Little' else finger)+str(soma)
clips={};sources=[]
for name,preset in [('wave','wave'),('happy','cheer'),('dance','dance'),('walk','walk_woman')]:
    source=LAB/f'image_to_3dlab/motions/{preset}.npz'
    rotations,joints,hips=module['load_motion'](source)
    indices=[module['SOMA_INDEX'][soma] for soma in mapping.values()]
    selected=rotations[:,indices]
    quaternions=Rotation.from_matrix(selected.reshape(-1,3,3)).as_quat().reshape(len(rotations),len(indices),4)
    if not np.allclose(np.linalg.norm(quaternions,axis=-1),1,atol=1e-6):
        raise RuntimeError('Motion quaternion normalization failed')
    height=float(module['soma_hip_height'](joints[None]))
    clips[name]=dict(fps=30,bones=list(mapping),quaternions=np.round(quaternions,6).tolist(),
                     hips=np.round(hips-hips[0],6).tolist(),hipHeight=height,
                     duration=len(rotations)/30)
    sources.append(dict(file=source.name,sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
out=ROOT/'web/assets/motions';out.mkdir(exist_ok=True)
(out/'conversation.json').write_text(json.dumps(dict(schema=1,axes='X left, Y up, Z forward',clips=clips),separators=(',',':'))+'\n')
(out/'source.json').write_text(json.dumps(dict(source='https://github.com/Bingeljell/image-to-3dlab',
    commit='91879333e88a0571945b15b0e21e4bc95ec59e31',
    producer='NVIDIA Kimodo-SOMA-RP-v1.1',license='NVIDIA Open Model License',
    note='Pre-generated output clips; no Kimodo runtime or language-model weights are needed.',files=sources),indent=2)+'\n')
print({name:dict(frames=len(clip['quaternions']),bones=len(clip['bones']),duration=clip['duration']) for name,clip in clips.items()})
