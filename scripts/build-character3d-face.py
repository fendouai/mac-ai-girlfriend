"""Reconstruct an expression-ready facial surface from the two GPT photographs.

Full-body landmarks locate the face; close-up landmarks supply detailed facial
depth and texture coordinates. Eye/mouth interiors are real openings, with separate
surfaces behind them. Outputs retain the facial vertex basis for later morph export.
"""
from pathlib import Path
import json
import runpy
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import cKDTree
from matplotlib.path import Path as Polygon
import trimesh

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'models/character3d-work'
TOPOLOGY=runpy.run_path(str(ROOT/'scripts/refine-character3d-hands.py'))
OVAL=[10,338,297,332,284,251,389,356,454,323,361,288,397,365,379,378,400,377,152,148,176,149,150,136,172,58,132,93,234,127,162,21,54,103,67,109]
MOUTH=[78,95,88,178,87,14,317,402,318,324,308,415,310,311,312,13,82,81,80,191]
EYES=[[33,7,163,144,145,153,154,155,133,173,157,158,159,160,161,246],
      [263,249,390,373,374,380,381,382,362,398,384,385,386,387,388,466]]
LOWER_LIP=[95,88,178,87,14,317,402,318,324,146,91,181,84,17,314,405,321,375]
UPPER_LIP=[191,80,81,82,13,312,311,310,415,185,40,39,37,0,267,269,270,409]


def main():
    body=trimesh.load(WORK/'sweet-refined-shape.glb',force='mesh')
    full=json.loads((WORK/'face-landmarks.json').read_text())
    portrait=json.loads((WORK/'portrait-landmarks.json').read_text())
    source=np.asarray(Image.open(ROOT/full['source']))
    labels,_=ndimage.label(source[:,:,3]>128);counts=np.bincount(labels.ravel());counts[0]=0
    yy,xx=np.nonzero(labels==counts.argmax())
    scale=body.extents[1]/(yy.max()-yy.min());cx=(xx.min()+xx.max())*.5
    lm=np.array(full['landmarks'])[:468];close=np.array(portrait['landmarks'])[:468]
    xy=np.column_stack(((lm[:,0]*full['width']-cx)*scale,
                        body.bounds[1,1]-(lm[:,1]*full['height']-yy.min())*scale))
    near=cKDTree(body.vertices[:,:2]).query(xy[1],k=80)[1]
    nose=float(np.quantile(body.vertices[near,2],.90))
    width=np.ptp(xy[:,0]);depth_scale=width/np.ptp(close[:,0])
    z=nose-(close[:,2]-close[1,2])*depth_scale
    vertices=np.column_stack((xy,z))
    faces=[]
    for line in (WORK/'canonical_face_model.obj').read_text().splitlines():
        p=line.split()
        if p and p[0]=='f':faces.append([int(x.split('/')[0])-1 for x in p[1:]])
    faces=np.array(faces)
    keep=np.ones(len(faces),bool)
    for ring in [MOUTH,*EYES]:keep &= ~np.isin(faces,ring).all(axis=1)
    faces=faces[keep]
    uv=close[:,:2].copy();uv[:,1]=1-uv[:,1]
    texture=Image.open(ROOT/portrait['source']).convert('RGB')
    material=trimesh.visual.material.PBRMaterial(name='GPT_portrait_skin',
                baseColorTexture=texture,metallicFactor=0,roughnessFactor=.72,doubleSided=True)
    face=trimesh.Trimesh(vertices,faces,process=False,
                visual=trimesh.visual.TextureVisuals(uv=uv,material=material))
    # The old neural surface has no usable eyelid/lip topology. Remove its front
    # face and connect the measured facial oval to that head opening.
    centers=body.triangles_center
    inside=Polygon(xy[OVAL]).contains_points(centers[:,:2])
    front=centers[:,2] > nose-width*.65
    trimmed=body.submesh([~(inside&front)],append=True,repair=False)
    loops=TOPOLOGY['boundary_loops'](trimmed)
    head_center=vertices[OVAL].mean(axis=0)
    old=min(loops,key=lambda loop:np.linalg.norm(trimmed.vertices[loop].mean(axis=0)-head_center))
    combined=np.vstack((trimmed.vertices,vertices))
    bridge_faces=TOPOLOGY['stitch'](old,[i+len(trimmed.vertices) for i in OVAL],combined,np.array([0,0,1]))
    bridge=trimesh.Trimesh(combined,bridge_faces,process=False)
    bridge.remove_unreferenced_vertices()
    # Keep the bridge as a separate primitive; it will receive the nearby head
    # material after body painting, while the measured face keeps the sharp photo.
    scene=trimesh.Scene();scene.add_geometry(trimmed,node_name='GeneratedBody')
    scene.add_geometry(face,node_name='MeasuredFace');scene.add_geometry(bridge,node_name='FaceBoundary')
    eyes=[]
    for index,ring in enumerate(EYES):
        center=vertices[ring].mean(axis=0)
        eye_width=np.ptp(vertices[ring,0]);radius=eye_width*.53
        center[2]-=radius*.8
        distance2=np.sum((vertices[:,:2]-center[:2])**2,axis=1)
        near_eye=distance2<radius*radius
        surface=center[2]+np.sqrt(np.maximum(0,radius*radius-distance2))+.0003
        vertices[near_eye,2]=np.maximum(vertices[near_eye,2],surface[near_eye])
        sphere=trimesh.creation.uv_sphere(radius=radius,count=[24,32]);sphere.apply_translation(center)
        p=close[ring];uv_center=p[:,:2].mean(axis=0)
        u=(sphere.vertices[:,0]-center[0])*np.ptp(p[:,0])/eye_width+uv_center[0]
        v=(sphere.vertices[:,1]-center[1])*np.ptp(p[:,1])/max(np.ptp(vertices[ring,1]),.001)
        v=1-(uv_center[1]-v)
        sphere.visual=trimesh.visual.TextureVisuals(uv=np.column_stack((u,v)),material=material)
        scene.add_geometry(sphere,node_name=f'Eye{index}')
        eyes.append(dict(center=center.tolist(),radius=radius,ring=ring))
    face.vertices=vertices
    lip=vertices[MOUTH].mean(axis=0)
    cavity=trimesh.creation.uv_sphere(radius=1,count=[16,24])
    cavity.apply_scale([width*.14,width*.075,width*.065])
    cavity.apply_translation(lip+np.array([0,-.002,-width*.055]))
    cavity.update_faces(cavity.triangles_center[:,2]<lip[2]-.004)
    cavity.remove_unreferenced_vertices()
    cavity.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            name='mouth_interior',baseColorFactor=[45,9,18,255],roughnessFactor=1,metallicFactor=0,doubleSided=True))
    scene.add_geometry(cavity,node_name='MouthInterior')
    morphs={}
    for name in ['aa','oh','ih','blink','happy','sad','relaxed']:
        delta=np.zeros_like(vertices)
        if name in ['aa','oh','ih']:
            center=vertices[13:15].mean(axis=0)
            dx=(vertices[:,0]-center[0])/(width*.27)
            dy=(vertices[:,1]-center[1])/(width*.20)
            weight=np.exp(-(dx*dx+dy*dy)*2)
            d_lower=cKDTree(vertices[LOWER_LIP,:2]).query(vertices[:,:2])[0]
            d_upper=cKDTree(vertices[UPPER_LIP,:2]).query(vertices[:,:2])[0]
            lower=d_upper/np.maximum(d_lower+d_upper,1e-8)
            lower[LOWER_LIP]=1;lower[UPPER_LIP]=0
            amount={'aa':.009,'oh':.006,'ih':.004}[name]
            delta[:,1]=-amount*weight*lower+.001*weight*(1-lower)
            delta[:,2]=-.0015*weight*lower
            if name=='oh':delta[:,0]=-(vertices[:,0]-center[0])*weight*.25
        elif name=='blink':
            for eye,ring in zip(eyes,EYES):
                center=vertices[ring].mean(axis=0)
                eye_width=np.ptp(vertices[ring,0]);eye_height=np.ptp(vertices[ring,1])
                dx=(vertices[:,0]-center[0])/(eye_width*.75)
                dy=(vertices[:,1]-center[1])/(max(eye_height,.001)*1.4)
                weight=np.exp(-(dx**4+dy**4)*2)
                delta[:,1]+=(center[1]-vertices[:,1])*weight
                for i in ring:delta[i,1]=center[1]-vertices[i,1]
                eyeball=np.array(eye['center']);radius=eye['radius']
                delta[:,2]+=.003*weight
                for i in ring:
                    dx=vertices[i,0]-eyeball[0]
                    delta[i,2]=max(0,eyeball[2]+np.sqrt(max(0,radius*radius-dx*dx))+.0007-vertices[i,2])
        elif name=='happy':
            for corner in [61,291]:
                d=np.linalg.norm(vertices[:,:2]-vertices[corner,:2],axis=1)/(width*.13)
                delta[:,1]+=.002*np.exp(-d*d*2)
        delta[OVAL]=0
        morphs[name]=delta.tolist()
    record=dict(vertices=vertices.tolist(),faces=faces.tolist(),uv=uv.tolist(),
                outer=OVAL,mouth=MOUTH,eyes=eyes,morphs=morphs,
                texture=str((ROOT/portrait['source']).resolve()),
                source='GPT full-body and portrait references; MediaPipe canonical topology (Apache-2.0)',
                face_width=width,nose_z=nose,
                projection=dict(worldPerPixel=scale,sourceCenterX=float(cx),sourceTopY=int(yy.min()),
                                worldTopY=float(body.bounds[1,1]),sourceWidth=full['width'],sourceHeight=full['height']))
    (WORK/'face-basis.json').write_text(json.dumps(record,separators=(',',':'))+'\n')
    scene.export(WORK/'sweet-face-preview.glb')
    print('Custom face:',len(vertices),'vertices',len(faces),'triangles, morphs',list(morphs),flush=True)


if __name__=='__main__':main()
