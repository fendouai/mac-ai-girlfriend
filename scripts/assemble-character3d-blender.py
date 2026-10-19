"""Blender: combine the generated body, measured facial rig and standard humanoid rest."""
from pathlib import Path
import sys
import json
import runpy
import numpy as np
import bpy
import bmesh
from mathutils import Matrix,Vector,kdtree

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'models/character3d-work'
LAB=ROOT/'third_party/assetfurnace'
sys.path.insert(0,str(ROOT/'scripts'))
from character3d_geometry import edge_loops,stitch_loops,inside_polygon

if not (WORK/'rig-provenance.json').exists():raise RuntimeError('Body binding and weight cleanup have not finished')
reference=json.loads((WORK/'face-basis.json').read_text())
retarget=runpy.run_path(str(LAB/'scripts/kimodo_retarget.py'))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(WORK/'sweet-rigged.glb'))
for obj in list(bpy.data.objects):
    if obj.type=='MESH' and obj.name.startswith('Icosphere'):bpy.data.objects.remove(obj,do_unlink=True)
arm=next(obj for obj in bpy.context.scene.objects if obj.type=='ARMATURE')
bodies=[obj for obj in bpy.context.scene.objects if obj.type=='MESH']
body=max(bodies,key=lambda obj:len(obj.data.polygons));body.name='SweetGeneratedBody'
# Rejoin UV-split copies geometrically; loop UVs and skin groups stay intact.
bm=bmesh.new();bm.from_mesh(body.data)
bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=1e-6)
bm.to_mesh(body.data);bm.free();body.data.update()
for polygon in body.data.polygons:polygon.use_smooth=True
parents={bone.name:bone.parent.name if bone.parent else None for bone in arm.data.bones}
rest={bone.name:np.array(bone.matrix_local) for bone in arm.data.bones}
heads={name:matrix[:3,3] for name,matrix in rest.items()}
up=np.array(arm.matrix_world.to_3x3().normalized()).T@np.array([0.,0.,1.])
mapping,frame=retarget['map_skintokens_to_soma'](parents,heads,up)
order=[name for name,parent in parents.items() if parent is None]
for name in order:order.extend(child.name for child in arm.data.bones[name].children)
global_rot,joints,_=retarget['load_motion'](LAB/'image_to_3dlab/motions/idle.npz')
tpose=retarget['soma_tpose'](global_rot[:1],joints[None])
align=retarget['rest_alignment'](parents,heads,mapping,retarget['soma_to_rig_axes'](frame),tpose)
world={name:align[name]@rest[name][:3,:3] for name in order}
basis=retarget['pose_basis'](rest,parents,order,world,rest[order[0]][:3,3])
for name,matrix in basis.items():
    arm.pose.bones[name].rotation_mode='QUATERNION';arm.pose.bones[name].matrix_basis=Matrix(matrix.tolist())
bpy.context.view_layer.update()
bpy.ops.object.select_all(action='DESELECT');body.select_set(True);bpy.context.view_layer.objects.active=body
modifier=next(mod for mod in body.modifiers if mod.type=='ARMATURE')
bpy.ops.object.modifier_apply(modifier=modifier.name)
bpy.ops.object.select_all(action='DESELECT');arm.select_set(True);bpy.context.view_layer.objects.active=arm
bpy.ops.object.mode_set(mode='POSE');bpy.ops.pose.armature_apply(selected=False);bpy.ops.object.mode_set(mode='OBJECT')
modifier=body.modifiers.new('Humanoid deformation','ARMATURE');modifier.object=arm
bpy.context.view_layer.update()
inverse={}
for name in order:inverse.setdefault(mapping[name],name)
head_name=inverse['Head']
# Clothing and skin are dielectric, matte surfaces. The image-to-PBR model's
# shiny metallic guess would make this human look like a plastic figurine.
for material in body.data.materials:
    if not material or not material.use_nodes:continue
    for node in material.node_tree.nodes:
        if node.type=='BSDF_PRINCIPLED':
            for key,value in [('Metallic',0),('Roughness',.76)]:
                for link in list(node.inputs[key].links):material.node_tree.links.remove(link)
                node.inputs[key].default_value=value
            if 'Coat Weight' in node.inputs:node.inputs['Coat Weight'].default_value=0
# Append only the facial assets, without the clay debugging body or seam.
with bpy.data.libraries.load(str(WORK/'sweet-facial-rig.blend'),link=False) as (available,loaded):
    loaded.objects=[name for name in available.objects if name=='FaceSurface' or name.startswith(('FaceEye','FaceMouth','FaceTooth'))]
facial=[]
for obj in loaded.objects:
    if obj is None:continue
    bpy.context.scene.collection.objects.link(obj)
    transform=obj.matrix_world.copy();obj.parent=None;obj.matrix_world=transform
    facial.append(obj)
face=next(obj for obj in facial if obj.name=='FaceSurface')
bm=bmesh.new();bm.from_mesh(face.data);bm.verts.ensure_lookup_table()
loops=edge_loops([(edge.verts[0].index,edge.verts[1].index) for edge in bm.edges if edge.is_boundary])
face_world=np.array([face.matrix_world@v.co for v in bm.verts])
outer=max(loops,key=lambda ids:np.linalg.norm(face_world[np.roll(ids,-1)]-face_world[ids],axis=1).sum())
inner_points=face_world[outer];center=inner_points.mean(axis=0)
bm.free()
polygon=inner_points[:,[0,2]];polygon_center=polygon.mean(axis=0)
polygon=(polygon-polygon_center)*1.08+polygon_center
bm=bmesh.new();bm.from_mesh(body.data);bm.faces.ensure_lookup_table()
centers=np.array([body.matrix_world@face.calc_center_median() for face in bm.faces])
inside=inside_polygon(centers[:,[0,2]],polygon)
front=centers[:,1]<-(reference['nose_z']-reference['face_width']*.65)
remove=[face for face,cut in zip(bm.faces,inside&front) if cut]
bmesh.ops.delete(bm,geom=remove,context='FACES')
bmesh.ops.delete(bm,geom=[v for v in bm.verts if not v.link_faces],context='VERTS')
bm.verts.index_update();bm.verts.ensure_lookup_table()
loops=edge_loops([(edge.verts[0].index,edge.verts[1].index) for edge in bm.edges if edge.is_boundary])
body_world=np.array([body.matrix_world@v.co for v in bm.verts])
old=min(loops,key=lambda ids:np.linalg.norm(body_world[ids].mean(axis=0)-center))
# Relax the jagged triangle cut while retaining the generated head surface.
old_points=body_world[old].copy()
# A face-centroid cut can leave a second small opening under the chin. Close
# those incidental cut loops; retain the main oval for the measured face.
uv_layer=bm.loops.layers.uv.active
for ring in loops:
    if ring is old:continue
    ids=set(ring)
    uv_by_vertex={i:bm.verts[i].link_loops[0][uv_layer].uv.copy() for i in ring}
    edges=[edge for edge in bm.edges if edge.is_boundary and all(v.index in ids for v in edge.verts)]
    filled=bmesh.ops.holes_fill(bm,edges=edges,sides=0)['faces']
    for polygon in filled:
        for loop in polygon.loops:loop[uv_layer].uv=uv_by_vertex[loop.vert.index]

for _ in range(6):
    old_points=.5*old_points+.25*np.roll(old_points,1,axis=0)+.25*np.roll(old_points,-1,axis=0)
# Keep both projected rings nested; otherwise a narrow seam can fold over itself.
center_xz=inner_points[:,[0,2]].mean(axis=0)
inner_q=inner_points[:,[0,2]]-center_xz
inner_angles=np.mod(np.arctan2(inner_q[:,1],inner_q[:,0]),2*np.pi)
order_angles=np.argsort(inner_angles)
for point in old_points:
    q=point[[0,2]]-center_xz;angle=np.mod(np.arctan2(q[1],q[0]),2*np.pi)
    radius=np.interp(angle,inner_angles[order_angles],np.linalg.norm(inner_q,axis=1)[order_angles],period=2*np.pi)*1.10
    point[[0,2]]=center_xz+q/np.linalg.norm(q)*max(np.linalg.norm(q),radius)
# Conform the perimeter depth to the generated skull, with zero correction at
# the central eyes/nose/mouth. Apply the same displacement to every morph key.
def ring_polar(points):
    q=points[:,[0,2]]-center_xz
    return np.mod(np.arctan2(q[:,1],q[:,0]),2*np.pi),np.linalg.norm(q,axis=1)
old_angle,old_radius=ring_polar(old_points)
inner_angle,inner_radius=ring_polar(inner_points)
order_old=np.argsort(old_angle);order_inner=np.argsort(inner_angle)
for index,point in zip(old,old_points):bm.verts[index].co=body.matrix_world.inverted()@Vector(point)
bm.to_mesh(body.data);bm.free();body.data.update()
# Bridge the measured oval to the generated head. Preserve actual boundary order.
joined=np.vstack([old_points,inner_points])
triangles=stitch_loops(list(range(len(old_points))),list(range(len(old_points),len(joined))),joined,np.array([0.,-1.,0.]),angular=True)
(WORK/'seam-debug.json').write_text(json.dumps(dict(old=old_points.tolist(),inner=inner_points.tolist(),triangles=triangles.tolist())))
mesh=bpy.data.meshes.new('Facial boundary surface');mesh.from_pydata(joined.tolist(),[],triangles.tolist());mesh.update()
bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(mesh);bm.free()
bridge=bpy.data.objects.new('FaceBoundarySurface',mesh);bpy.context.scene.collection.objects.link(bridge)
bpy.ops.object.select_all(action='DESELECT');bridge.select_set(True);bpy.context.view_layer.objects.active=bridge
# A thin-plate projection extends the actual facial UVs smoothly onto the skull.
# Use it on both sides of the seam, fading into the generated body material.
landmarks=np.array(reference['vertices'])[:,[0,1]]
landmark_uv=np.array(reference['uv'])
def radial_kernel(distance):
    square=distance*distance
    return square*np.log(np.maximum(distance,1e-9))
distances=np.linalg.norm(landmarks[:,None]-landmarks[None],axis=2)
poly=np.column_stack([np.ones(len(landmarks)),landmarks])
system=np.block([[radial_kernel(distances)+np.eye(len(landmarks))*1e-9,poly],[poly.T,np.zeros((3,3))]])
coeff=np.linalg.solve(system,np.vstack([landmark_uv,np.zeros((3,2))]))
def project(points):
    result=[]
    for start in range(0,len(points),512):
        chunk=points[start:start+512]
        design=np.column_stack([radial_kernel(np.linalg.norm(chunk[:,None]-landmarks[None],axis=2)),np.ones(len(chunk)),chunk])
        result.append(design@coeff)
    return np.vstack(result)
bridge.data.materials.append(face.data.materials[0])
uv=bridge.data.uv_layers.new(name=face.data.uv_layers[0].name)
projected=project(np.array([v.co for v in bridge.data.vertices])[:,[0,2]])
for loop in bridge.data.loops:uv.data[loop.index].uv=projected[loop.vertex_index]
# The skull material blends through the same projection outside the welded oval.
body_uv=body.data.uv_layers.new(name='PortraitProjection')
coords=np.array([v.co for v in body.data.vertices]);angles,radii=ring_polar(coords)
edge_radii=np.interp(angles,inner_angle[order_inner],inner_radius[order_inner],period=2*np.pi)
weight=np.clip((1.60-radii/np.maximum(edge_radii,1e-6))/.45,0,1)
weight*=np.clip((-.015-coords[:,1])/.04,0,1)
projected=np.zeros((len(coords),2));selected=np.flatnonzero(weight>0)
projected[selected]=project(coords[selected][:,[0,2]])
attribute=body.data.color_attributes.new(name='PortraitBlend',type='FLOAT_COLOR',domain='POINT')
for i,w in enumerate(weight):attribute.data[i].color=(w,w,w,1)
for loop in body.data.loops:body_uv.data[loop.index].uv=projected[loop.vertex_index]
for material in body.data.materials:
    if not material or not material.use_nodes:continue
    nodes=material.node_tree.nodes;links=material.node_tree.links
    shader=next(n for n in nodes if n.type=='BSDF_PRINCIPLED')
    original=shader.inputs['Base Color'].links[0].from_socket
    portrait=nodes.new('ShaderNodeTexImage');portrait.image=next(n.image for n in face.data.materials[0].node_tree.nodes if n.type=='TEX_IMAGE')
    uv_node=nodes.new('ShaderNodeUVMap');uv_node.uv_map='PortraitProjection';links.new(uv_node.outputs['UV'],portrait.inputs['Vector'])
    factor=nodes.new('ShaderNodeVertexColor');factor.layer_name='PortraitBlend'
    mix=nodes.new('ShaderNodeMixRGB');links.new(factor.outputs['Color'],mix.inputs[0]);links.new(original,mix.inputs[1]);links.new(portrait.outputs['Color'],mix.inputs[2]);links.new(mix.outputs[0],shader.inputs['Base Color'])
# Skin colour on the small generated palms is unreliable. Repaint those
# anatomical template surfaces in the same skin tone as the generated portrait,
# fading by the real hand/finger skin weights through each wrist.
hand_groups={group.index for group in body.vertex_groups if mapping.get(group.name,'').startswith(('LeftHand','RightHand'))}
hand_color=body.data.color_attributes.new(name='HandSkinBlend',type='FLOAT_COLOR',domain='POINT')
for vertex in body.data.vertices:
    strength=min(1,sum(group.weight for group in vertex.groups if group.group in hand_groups))
    hand_color.data[vertex.index].color=(strength,strength,strength,1)
portrait_image=next(n.image for n in face.data.materials[0].node_tree.nodes if n.type=='TEX_IMAGE')
pixels=np.array(portrait_image.pixels[:]).reshape(portrait_image.size[1],portrait_image.size[0],4)
colors=[]
for index in [50,280,101,330]:
    u,v=reference['uv'][index];color=pixels[int(v*(portrait_image.size[1]-1)),int(u*(portrait_image.size[0]-1)),:3]
    colors.append(np.where(color<=.04045,color/12.92,((color+.055)/1.055)**2.4))
skin=np.mean(colors,axis=0)
for material in body.data.materials:
    nodes=material.node_tree.nodes;links=material.node_tree.links
    shader=next(n for n in nodes if n.type=='BSDF_PRINCIPLED');original=shader.inputs['Base Color'].links[0].from_socket
    factor=nodes.new('ShaderNodeVertexColor');factor.layer_name='HandSkinBlend'
    mix=nodes.new('ShaderNodeMixRGB');mix.inputs[2].default_value=(*skin,1)
    links.new(factor.outputs['Color'],mix.inputs[0]);links.new(original,mix.inputs[1]);links.new(mix.outputs[0],shader.inputs['Base Color'])
# Bake the mixed projection into one standard glTF base-colour atlas. Shader
# mixing is an authoring operation; the browser receives an ordinary PBR texture.
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=1
scene.render.bake.use_pass_direct=False;scene.render.bake.use_pass_indirect=False;scene.render.bake.use_pass_color=True
baked=bpy.data.images.new('Custom skin seamless albedo',width=4096,height=4096,alpha=False)
for material in body.data.materials:
    target=material.node_tree.nodes.new('ShaderNodeTexImage');target.image=baked
    material.node_tree.nodes.active=target
body.data.uv_layers.active=body.data.uv_layers[0]
body.data.uv_layers[0].active_render=True
bpy.ops.object.select_all(action='DESELECT');body.select_set(True);bpy.context.view_layer.objects.active=body
bpy.ops.object.bake(type='DIFFUSE',pass_filter={'COLOR'},margin=8,use_clear=True)
baked.filepath_raw=str(WORK/'sweet-seamless-albedo.png');baked.file_format='PNG';baked.save();baked.pack()
for material in body.data.materials:
    nodes=material.node_tree.nodes;links=material.node_tree.links
    shader=next(n for n in nodes if n.type=='BSDF_PRINCIPLED')
    texture=nodes.new('ShaderNodeTexImage');texture.image=baked
    uv_node=nodes.new('ShaderNodeUVMap');uv_node.uv_map=body.data.uv_layers[0].name
    links.new(uv_node.outputs['UV'],texture.inputs['Vector']);links.new(texture.outputs['Color'],shader.inputs['Base Color'])
body.data.color_attributes.remove(body.data.color_attributes['PortraitBlend'])
body.data.color_attributes.remove(body.data.color_attributes['HandSkinBlend'])
facial.append(bridge)
for obj in facial:
    weight=obj.vertex_groups.new(name=head_name);weight.add(list(range(len(obj.data.vertices))),1,'REPLACE')
    modifier=obj.modifiers.new('Follow head skeleton','ARMATURE');modifier.object=arm
    for polygon in obj.data.polygons:polygon.use_smooth=True
    if obj.name.startswith('FaceEye'):
        material=obj.data.materials[0].copy();obj.data.materials[0]=material
        for node in material.node_tree.nodes:
            if node.type=='BSDF_PRINCIPLED':node.inputs['Roughness'].default_value=.25
# Join and weld the complete skin. Keeping coplanar seam pieces separate creates
# cracks and conflicting normals after skinning; Blender retains all facial keys
# while filling neutral coordinates for the body and seam vertices.
bpy.ops.object.select_all(action='DESELECT')
for obj in [body,face,bridge]:obj.select_set(True)
bpy.context.view_layer.objects.active=face
bpy.ops.object.join()
if face.data.has_custom_normals:bpy.ops.mesh.customdata_custom_splitnormals_clear()
bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.remove_doubles(threshold=.00002)
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.object.mode_set(mode='OBJECT')
# Relax the entire joined junction, including adjacent original vertices. Smoothing
# only the connecting strip leaves a raised rim at either end of that strip.
coords=np.array([v.co for v in face.data.vertices]);angles,radii=ring_polar(coords)
edge_radii=np.interp(angles,inner_angle[order_inner],inner_radius[order_inner],period=2*np.pi)
ratio=radii/np.maximum(edge_radii,1e-6)
weights=np.clip((ratio-.60)/.25,0,1)*np.clip((1.6-ratio)/.4,0,1)*np.clip((-.01-coords[:,1])/.04,0,1)
edges=np.array([edge.vertices[:] for edge in face.data.edges]);degree=np.bincount(edges.ravel(),minlength=len(coords))
original_coords=coords.copy()
for _ in range(45):
    sums=np.zeros_like(coords)
    np.add.at(sums,edges[:,0],coords[edges[:,1]]);np.add.at(sums,edges[:,1],coords[edges[:,0]])
    average=sums/np.maximum(degree[:,None],1)
    coords+=(average-coords)*weights[:,None]*.45
correction=coords-original_coords
for key in face.data.shape_keys.key_blocks:
    for vertex,delta in zip(key.data,correction):vertex.co+=Vector(delta)
for vertex,co in zip(face.data.vertices,coords):vertex.co=co
for polygon in face.data.polygons:polygon.use_smooth=True
body=face
facial=[obj for obj in facial if obj is not bridge]
# Only the two eyes and the mouth may remain open; every skull junction must
# be connected. This catches T junctions introduced by independent subdivision.
bpy.context.view_layer.objects.active=face
bpy.ops.object.mode_set(mode='EDIT')
bm=bmesh.from_edit_mesh(face.data);bm.verts.index_update();bm.verts.ensure_lookup_table()
openings=edge_loops([(edge.verts[0].index,edge.verts[1].index) for edge in bm.edges if edge.is_boundary])
expected=[np.array(reference['vertices'])[reference['mouth']].mean(axis=0)[[0,2,1]]*np.array([1,-1,1])]
for eye in reference['eyes']:
    expected.append(np.array(reference['vertices'])[eye['ring']].mean(axis=0)[[0,2,1]]*np.array([1,-1,1]))
centers=[np.array([bm.verts[i].co for i in ring]).mean(axis=0) for ring in openings]
keep={min(range(len(openings)),key=lambda i:np.linalg.norm(centers[i]-point)) for point in expected}
print('BOUNDARY_LOOPS',[(len(ring),centers[i].tolist(),i in keep) for i,ring in enumerate(openings)],flush=True)
for index,ring in enumerate(openings):
    if index in keep:continue
    ids=set(ring);edges=[e for e in bm.edges if e.is_boundary and all(v.index in ids for v in e.verts)]
    uv_layers=list(bm.loops.layers.uv.values())
    uv_by_vertex={i:[bm.verts[i].link_loops[0][layer].uv.copy() for layer in uv_layers] for i in ring}
    material=edges[0].link_faces[0].material_index
    center_vertex=bm.verts.new(Vector(centers[index]));bm.verts.ensure_lookup_table()
    for layer in bm.verts.layers.shape.values():center_vertex[layer]=center_vertex.co.copy()
    deform=bm.verts.layers.deform.active
    if deform:center_vertex[deform][face.vertex_groups[head_name].index]=1
    center_uv=[sum((uv_by_vertex[i][j] for i in ring),Vector((0,0)))/len(ring) for j in range(len(uv_layers))]
    for i,a in enumerate(ring):
        b=ring[(i+1)%len(ring)];va,vb=bm.verts[a],bm.verts[b]
        edge=next(e for e in va.link_edges if vb in e.verts)
        adjacent=next(loop for loop in edge.link_faces[0].loops if loop.edge is edge)
        vertices=(vb,va,center_vertex) if adjacent.vert is va else (va,vb,center_vertex)
        polygon=bm.faces.new(vertices);polygon.material_index=material;polygon.smooth=True
        for loop in polygon.loops:
            values=center_uv if loop.vert is center_vertex else uv_by_vertex[loop.vert.index]
            for layer,value in zip(uv_layers,values):loop[layer].uv=value
    print('CLOSED_JUNCTION',len(edges),len(ring),flush=True)
bmesh.update_edit_mesh(face.data);bpy.ops.object.mode_set(mode='OBJECT')
bm=bmesh.new();bm.from_mesh(face.data);bm.verts.index_update()
openings=edge_loops([(edge.verts[0].index,edge.verts[1].index) for edge in bm.edges if edge.is_boundary])
if len(openings)!=3:raise RuntimeError(f'Unexpected facial boundary loops: {len(openings)}')
bm.free()
for key in face.data.shape_keys.key_blocks:
    if not np.isfinite(np.array([v.co for v in key.data])).all():raise RuntimeError(f'Nonfinite facial key: {key.name}')
# Export a standards-based bone map; all other generated bones remain in the skin.
human=dict(hips='Hips',spine='Spine1',chest='Spine2',upperChest='Chest',neck='Neck2',head='Head')
for side in ['left','right']:
    title=side.title()
    for bone,soma in [('Shoulder','Shoulder'),('UpperArm','Arm'),('LowerArm','ForeArm'),('Hand','Hand'),('UpperLeg','Leg'),('LowerLeg','Shin'),('Foot','Foot'),('Toes','ToeBase')]:human[side+bone]=title+soma
    for bone,index in [('Metacarpal',1),('Proximal',2),('Distal',3)]:human[side+'Thumb'+bone]=title+'HandThumb'+str(index)
    for finger in ['Index','Middle','Ring','Little']:
        for bone,index in [('Proximal',2),('Intermediate',3),('Distal',4)]:human[side+finger+bone]=title+'Hand'+('Pinky' if finger=='Little' else finger)+str(index)
mapped={name:inverse[soma] for name,soma in human.items() if soma in inverse}
if 'spine' not in mapped:
    mapped['spine']=inverse.get('Spine2',inverse.get('Chest'))
if 'neck' not in mapped and 'Neck1' in inverse:mapped['neck']=inverse['Neck1']
required=['hips','spine','head','leftUpperArm','leftLowerArm','leftHand','rightUpperArm','rightLowerArm','rightHand','leftUpperLeg','leftLowerLeg','leftFoot','rightUpperLeg','rightLowerLeg','rightFoot']
if any(not mapped.get(name) for name in required):raise RuntimeError('Generated skeleton is missing a required humanoid bone')
for side in ['left','right']:
    upper=arm.matrix_world@arm.data.bones[mapped[side+'UpperArm']].head_local
    elbow=arm.matrix_world@arm.data.bones[mapped[side+'LowerArm']].head_local
    direction=(elbow-upper).normalized()
    if abs(direction.x)<.95:raise RuntimeError(f'{side} arm did not reach the standard T rest pose')
output=WORK/'sweet-final-rig.glb'
bpy.ops.object.select_all(action='DESELECT');arm.select_set(True);body.select_set(True)
for obj in facial:obj.select_set(True)
bpy.context.view_layer.objects.active=arm
bpy.ops.export_scene.gltf(filepath=str(output),export_format='GLB',use_selection=True,
                         export_skins=True,export_morph=True,export_animations=False)
bpy.ops.wm.save_as_mainfile(filepath=str(WORK/'sweet-final-rig.blend'))
metadata=dict(humanoid=mapped,soma_mapping=mapping,face_object=face.name,
              head_bone=head_name,body_vertices=len(body.data.vertices),face_vertices=len(face.data.vertices),
              source='GPT references -> MLX surface/PBR -> anatomical hands -> SkinTokens -> measured facial morphs')
(WORK/'final-rig-map.json').write_text(json.dumps(metadata,indent=2)+'\n')
print('CUSTOM_AVATAR_ASSEMBLED',json.dumps(metadata),flush=True)
