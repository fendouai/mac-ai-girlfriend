"""Fit CC0 anatomical finger topology to both GPT-photo hands and stitch the wrists.

The generated torso, clothes, legs and hair remain the Hunyuan surface. The hand
template supplies separate fingers; 21 measured points per hand supply its pose.
"""
from pathlib import Path
import json
from collections import defaultdict
import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation
from scipy import ndimage
import trimesh
from character3d_geometry import stitch_loops as stitch

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT/'models/character3d-work'


def read_template():
    verts, faces, group = [], [], ''
    for line in (WORK/'makehuman-base.obj').read_text().splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == 'v':
            verts.append(list(map(float, fields[1:4])))
        elif fields[0] == 'g':
            group = fields[1]
        elif fields[0] == 'f' and group == 'body':
            ids = [int(x.split('/')[0])-1 for x in fields[1:]]
            faces.extend([[ids[0], ids[i], ids[i+1]] for i in range(1,len(ids)-1)])
    return np.array(verts), np.array(faces)


def unit(v):
    return v/max(np.linalg.norm(v),1e-10)


def boundary_loops(mesh):
    edges = mesh.edges_sorted
    unique, counts = np.unique(edges,axis=0,return_counts=True)
    links = defaultdict(list)
    for a,b in unique[counts==1]:
        links[int(a)].append(int(b)); links[int(b)].append(int(a))
    loops=[]
    while links:
        start=next(iter(links)); loop=[start]; previous=None; node=start
        for _ in range(len(links)+2):
            neighbours=links[node]
            nxt=next((x for x in neighbours if x!=previous),start)
            if nxt==start:
                break
            loop.append(nxt);previous,node=node,nxt
        for node in loop:
            links.pop(node,None)
        if len(loop)>=3:
            loops.append(loop)
    return loops


def main():
    original=trimesh.load(WORK/'sweet-shape.glb',force='mesh')
    canonical,template_faces=read_template()
    rig=json.loads((WORK/'makehuman-default.mhskel').read_text())
    weights=json.loads((WORK/'makehuman-default-weights.mhw').read_text())['weights']
    hands=json.loads((WORK/'hand-landmarks.json').read_text())['hands']
    source=np.asarray(Image.open(ROOT/'data/avatars/generated/sweet-3d-front-v1.png'))
    labels,_=ndimage.label(source[:,:,3]>128)
    sizes=np.bincount(labels.ravel());sizes[0]=0
    yy,xx=np.nonzero(labels==sizes.argmax())
    scale=original.extents[1]/(yy.max()-yy.min())
    center_x=(xx.min()+xx.max())*.5
    joint=lambda name:canonical[rig['joints'][name]].mean(axis=0)
    refined={}; specs={}
    for side,record in hands.items():
        points=np.array(record['landmarks'])
        target=np.column_stack(((points[:,0]*source.shape[1]-center_x)*scale,
                                original.bounds[1,1]-(points[:,1]*source.shape[0]-yy.min())*scale,
                                -points[:,2]*source.shape[1]*scale))
        nearest=np.argsort(np.linalg.norm(original.vertices[:,:2]-target[0,:2],axis=1))[:30]
        target[:,2]+=np.median(original.vertices[nearest,2])
        source_joints=[joint(f'wrist.{side}____head')]
        for finger in range(1,6):
            source_joints.extend([joint(f'finger{finger}-{k}.{side}____head') for k in range(1,4)])
            source_joints.append(joint(f'finger{finger}-3.{side}____tail'))
        source_joints=np.array(source_joints)
        centered_source=source_joints-source_joints[0]
        centered_target=target-target[0]
        r,_=Rotation.align_vectors(centered_target,centered_source)
        rotation=r.as_matrix()
        hand_scale=np.linalg.norm(centered_target[9])/np.linalg.norm(centered_source[9])
        bones=([f'wrist.{side}']+[f'metacarpal{k}.{side}' for k in range(1,5)]
               +[f'finger{f}-{k}.{side}' for f in range(1,6) for k in range(1,4)])
        hand_weight=np.zeros(len(canonical))
        for bone in bones:
            for index,weight in weights[bone]:hand_weight[index]+=weight
        selected=hand_weight>.025
        faces=template_faces[selected[template_faces].all(axis=1)]
        output=np.zeros_like(canonical)
        for bone in bones:
            if bone.startswith(('wrist','metacarpal')):
                origin=source_joints[0];anchor=target[0];matrix=rotation*hand_scale
            else:
                f=int(bone[6]);k=int(bone[8]);index=1+(f-1)*4+k-1
                origin=source_joints[index];anchor=target[index]
                direction=source_joints[index+1]-origin
                wanted=target[index+1]-anchor
                correction,_=Rotation.align_vectors([unit(wanted)],[unit(rotation@direction)])
                axial=np.linalg.norm(wanted)/np.linalg.norm(direction)
                axis=unit(direction)
                matrix=correction.as_matrix()@rotation@(np.eye(3)*hand_scale+np.outer(axis,axis)*(axial-hand_scale))
            for index,weight in weights[bone]:
                output[index]+=(matrix@(canonical[index]-origin)+anchor)*weight/max(hand_weight[index],1e-10)
        hand=trimesh.Trimesh(vertices=output,faces=faces,process=False)
        hand.remove_unreferenced_vertices()
        hand=max(hand.split(only_watertight=False),key=lambda x:len(x.faces))
        axis=target[9]-target[0];axis[2]=0;axis=unit(axis);wrist=target[0]
        refined[side]=hand;specs[side]=(wrist,axis)
    centers=original.triangles_center
    keep=np.ones(len(original.faces),bool)
    for side,(wrist,axis) in specs.items():
        signed=(centers-wrist)@axis
        region=(np.abs(centers[:,0])>.35)&(np.linalg.norm(centers-wrist,axis=1)<.3)
        keep &= ~(region & (signed>-.006))
    body=original.submesh([keep],append=True,repair=False)
    body_loops=boundary_loops(body)
    vertices=list(body.vertices);faces=list(body.faces);stitches=[]
    for side,hand in refined.items():
        wrist,axis=specs[side]
        old_loop=min(body_loops,key=lambda loop:np.linalg.norm(body.vertices[loop].mean(axis=0)-wrist))
        new_loop=min(boundary_loops(hand),key=lambda loop:np.linalg.norm(hand.vertices[loop].mean(axis=0)-wrist))
        offset=len(vertices);vertices.extend(hand.vertices);faces.extend(hand.faces+offset)
        stitches.extend(stitch(old_loop,[i+offset for i in new_loop],np.array(vertices),axis))
    faces.extend(stitches)
    result=trimesh.Trimesh(vertices=vertices,faces=faces,process=True)
    # A weight-threshold cut can leave a few small four/six-edge gaps near a
    # metacarpal. Close those local gaps before relaxing the stitched cuffs.
    gaps=boundary_loops(result)
    gap_vertices=list(result.vertices);gap_faces=list(result.faces)
    for loop in gaps:
        if len(loop)>12:
            raise RuntimeError(f'Unexpected large open seam: {len(loop)} edges')
        index=len(gap_vertices);gap_vertices.append(result.vertices[loop].mean(axis=0))
        gap_faces.extend([[loop[i],loop[(i+1)%len(loop)],index] for i in range(len(loop))])
    result=trimesh.Trimesh(vertices=gap_vertices,faces=gap_faces,process=True)
    trimesh.repair.fix_normals(result,multibody=True)
    near=np.zeros(len(result.vertices),bool)
    for wrist,_ in specs.values():
        near |= np.linalg.norm(result.vertices-wrist,axis=1)<.055
    laplacian=trimesh.smoothing.laplacian_calculation(result,pinned_vertices=np.flatnonzero(~near))
    trimesh.smoothing.filter_laplacian(result,lamb=.35,iterations=10,
                                      volume_constraint=False,laplacian_operator=laplacian)
    if not result.is_watertight:
        edges,counts=np.unique(result.edges_sorted,axis=0,return_counts=True)
        raise RuntimeError(f'Hand surface invalid: {int((counts==1).sum())} boundary, {int((counts>2).sum())} nonmanifold edges')
    result.export(WORK/'sweet-refined-shape.glb');result.export(WORK/'sweet-refined-shape.obj')
    stats=dict(vertices=len(result.vertices),faces=len(result.faces),watertight=bool(result.is_watertight),
               hand_faces={s:len(m.faces) for s,m in refined.items()},wrist_bridge_faces=len(stitches),
               template='MakeHuman base hands, CC0',source='21 MediaPipe points per GPT photo hand')
    (WORK/'hands-provenance.json').write_text(json.dumps(stats,indent=2)+'\n')
    print(json.dumps(stats,indent=2),flush=True)


if __name__=='__main__':main()
