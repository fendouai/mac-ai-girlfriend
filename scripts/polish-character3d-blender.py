"""Refine the generated surface and split physically different material regions.

No generation weights are loaded. Skin groups, portrait UVs and every facial
shape key survive the same volume-preserving surface correction.
"""
from pathlib import Path
import json

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'models/character3d-work'
bpy.ops.wm.open_mainfile(filepath=str(WORK / 'sweet-final-rig.blend'))
body = bpy.data.objects['FaceSurface']
mesh = body.data
original_material = mesh.materials[1]
shader = next(n for n in original_material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
image = shader.inputs['Base Color'].links[0].from_node.image
pixels = np.array(image.pixels[:]).reshape(image.size[1], image.size[0], 4)
uv = mesh.uv_layers['UVMap'].data
mapping = json.loads((WORK / 'final-rig-map.json').read_text())['soma_mapping']
hand_groups = {g.index for g in body.vertex_groups if mapping.get(g.name, '').startswith(('LeftHand', 'RightHand'))}
hand_weight = np.array([sum(g.weight for g in v.groups if g.group in hand_groups) for v in mesh.vertices])


def material(name, template, roughness, specular, sheen=0, anisotropy=0):
    result = template.copy()
    result.name = name
    node = next(n for n in result.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    for key, value in [('Roughness', roughness), ('Metallic', 0),
                       ('Specular IOR Level', specular), ('Sheen Weight', sheen),
                       ('Sheen Roughness', .8), ('Anisotropic IOR Level', anisotropy)]:
        if key in node.inputs:
            for link in list(node.inputs[key].links):result.node_tree.links.remove(link)
            node.inputs[key].default_value = value
    return result


materials = [material('AvatarSkinPortrait', mesh.materials[0], .56, .3),
             material('AvatarKnit', original_material, .9, .25, sheen=.10),
             material('AvatarHair', original_material, .4, .55, anisotropy=.55),
             material('AvatarTrousers', original_material, .85, .25, sheen=.12),
             material('AvatarShoes', original_material, .65, .3),
             material('AvatarSkinHands', original_material, .56, .3)]
categories = []
for polygon in mesh.polygons:
    if polygon.material_index == 0:
        categories.append(0)
        continue
    vertices = np.array(polygon.vertices)
    center = np.mean([mesh.vertices[i].co for i in vertices], axis=0)
    sample_uv = np.mean([uv[i].uv for i in polygon.loop_indices], axis=0)
    x, y = np.clip(sample_uv * np.array(image.size), 0, np.array(image.size) - 1).astype(int)
    color = pixels[y, x, :3]
    if hand_weight[vertices].mean() > .35:
        category = 5
    elif center[2] > .0 and color.max() < .52 and color[0] > color[2] * .9:
        category = 2
    elif center[2] < -.86:
        category = 4
    elif center[2] < -.025:
        category = 3
    else:
        category = 1
    categories.append(category)
mesh.materials.clear()
for entry in materials:mesh.materials.append(entry)
for polygon, category in zip(mesh.polygons, categories):polygon.material_index = category

# Taubin lambda/mu pairs suppress short-scale reconstruction noise while keeping
# the body's volume. Protect all facial topology and the anatomical fingers.
coords = np.array([v.co for v in mesh.vertices])
initial = coords.copy()
edges = np.array([e.vertices[:] for e in mesh.edges])
degree = np.bincount(edges.ravel(), minlength=len(coords))
weights = np.zeros(len(coords))
for polygon, category in zip(mesh.polygons, categories):
    weight = {0: 0, 1: 1, 2: .65, 3: 1, 4: .25, 5: 0}[category]
    for index in polygon.vertices:weights[index] = max(weights[index], weight)
weights *= np.clip((.7 - hand_weight) / .4, 0, 1)
for _ in range(16):
    for factor in [.48, -.5]:
        sums = np.zeros_like(coords)
        np.add.at(sums, edges[:, 0], coords[edges[:, 1]])
        np.add.at(sums, edges[:, 1], coords[edges[:, 0]])
        coords += factor * weights[:, None] * (sums / np.maximum(1, degree[:, None]) - coords)
delta = coords - initial
distance = np.linalg.norm(delta, axis=1)
# Bound isolated reconstruction outliers: a cosmetic pass must not change the
# silhouette or move an anatomical feature by centimetres.
delta *= np.minimum(1, .008 / np.maximum(distance, 1e-9))[:, None]
coords = initial + delta
assert np.isfinite(coords).all()
for key in mesh.shape_keys.key_blocks:
    for vertex, offset in zip(key.data, delta):vertex.co += Vector(offset)
for vertex, position in zip(mesh.vertices, coords):vertex.co = position
if mesh.has_custom_normals:
    bpy.context.view_layer.objects.active = body
    bpy.ops.mesh.customdata_custom_splitnormals_clear()
for polygon in mesh.polygons:polygon.use_smooth = True
mesh.update()

# Fine strand geometry breaks up the smooth reconstructed hair shell. Trace a
# downward tangent field on its largest connected hair region, then skin each
# strand to the nearest original surface weights. Seed and taper are deterministic.
hair_polygons=[p for p in mesh.polygons if p.material_index==2]
links={};parents=list(range(len(hair_polygons)))
def find(i):
    while parents[i]!=i:parents[i]=parents[parents[i]];i=parents[i]
    return i
for i,polygon in enumerate(hair_polygons):
    for edge in polygon.edge_keys:
        if edge in links:parents[find(i)]=find(links[edge])
        else:links[edge]=i
components={}
for i in range(len(hair_polygons)):components.setdefault(find(i),[]).append(i)
largest=max(components.values(),key=len)
hair_polygons=[hair_polygons[i] for i in largest]
hair_vertices={index for polygon in hair_polygons for index in polygon.vertices}
# Proximity-based auto-binding can attach hanging hair to an upper arm. Keep
# scalp and long locks on the head/torso so a bent elbow cannot pull out a spike.
inverse={value:key for key,value in mapping.items()}
head_group=body.vertex_groups[inverse['Head']]
chest_group=body.vertex_groups[inverse['Chest']]
arm_groups={g.index for g in body.vertex_groups if any(word in mapping.get(g.name,'') for word in ['Arm','Hand'])}
hair_arm_bindings=sum(any(g.group in arm_groups and g.weight>.05 for g in mesh.vertices[i].groups) for i in hair_vertices)
hair_ids=list(hair_vertices)
for group in body.vertex_groups:group.remove(hair_ids)
for index in hair_ids:
    height=mesh.vertices[index].co.z
    t=float(np.clip((height-.2)/.55,0,1));head_weight=.15+.85*t*t*(3-2*t)
    head_group.add([index],head_weight,'REPLACE');chest_group.add([index],1-head_weight,'REPLACE')
surface=BVHTree.FromPolygons([v.co for v in mesh.vertices],[list(p.vertices) for p in hair_polygons])
tree=KDTree(len(mesh.vertices))
for v in mesh.vertices:tree.insert(v.co,v.index)
tree.balance()
rng=np.random.default_rng(42)
eligible=[p for p in hair_polygons if p.center.z>.25]
strand_vertices=[];strand_faces=[];strand_weights=[];strand_count=0
for _ in range(480):
    polygon=eligible[int(rng.integers(len(eligible)))];start=polygon.center.copy()
    start+=Vector(rng.normal(0,.001,3))
    points=[];normals=[];p=start
    for step in range(int(rng.integers(22,52))):
        co,normal,_,distance=surface.find_nearest(p)
        if co is None or distance>.015 or co.z<.08:break
        points.append(co+normal*(.0004+.0004*step/52));normals.append(normal)
        down=Vector((.025 if co.x>0 else -.025,0,-1))
        tangent=down-normal*down.dot(normal)
        if tangent.length<.03:break
        p=co+tangent.normalized()*.0055
    if len(points)<8:continue
    offset=len(strand_vertices);radius=float(rng.uniform(.00013,.00026))
    for j,(point,normal) in enumerate(zip(points,normals)):
        direction=(points[min(j+1,len(points)-1)]-points[max(0,j-1)]).normalized()
        normal=(normal-direction*normal.dot(direction)).normalized();side=direction.cross(normal)
        taper=max(.08,(1-j/len(points))**.6)
        _,nearest,_=tree.find(point)
        weights=[(g.group,g.weight) for g in mesh.vertices[nearest].groups]
        for k in range(3):
            angle=k*2*np.pi/3
            strand_vertices.append(point+radius*taper*(normal*np.cos(angle)+side*np.sin(angle)))
            strand_weights.append(weights)
        if j:
            for k in range(3):
                a=offset+(j-1)*3+k;b=offset+(j-1)*3+(k+1)%3;c=offset+j*3+k;d=offset+j*3+(k+1)%3
                strand_faces.extend([(a,b,c),(b,d,c)])
    strand_count+=1
hair_mesh=bpy.data.meshes.new('Fine hair strand geometry');hair_mesh.from_pydata(strand_vertices,[],strand_faces);hair_mesh.update()
hair_obj=bpy.data.objects.new('AvatarFineHair',hair_mesh);bpy.context.scene.collection.objects.link(hair_obj)
hair_material=bpy.data.materials.new('AvatarHairStrands');hair_material.use_nodes=True
hair_shader=hair_material.node_tree.nodes.get('Principled BSDF')
hair_shader.inputs['Base Color'].default_value=(.045,.019,.011,1);hair_shader.inputs['Roughness'].default_value=.55
hair_mesh.materials.append(hair_material)
for group in body.vertex_groups:hair_obj.vertex_groups.new(name=group.name)
for i,weights in enumerate(strand_weights):
    for group,weight in weights:hair_obj.vertex_groups[group].add([i],weight,'REPLACE')
modifier=hair_obj.modifiers.new('Follow original hair skin','ARMATURE')
modifier.object=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
for polygon in hair_mesh.polygons:polygon.use_smooth=True

output = WORK / 'sweet-polished.glb'
bpy.ops.object.select_all(action='DESELECT')
for obj in bpy.context.scene.objects:
    if obj.type in ['MESH', 'ARMATURE']:obj.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.export_scene.gltf(filepath=str(output), export_format='GLB', use_selection=True,
                         export_skins=True, export_morph=True, export_animations=False)
bpy.ops.wm.save_as_mainfile(filepath=str(WORK / 'sweet-polished.blend'))
record = dict(method='Taubin lambda/mu volume-preserving surface refinement',
              iterations=16, vertices=len(coords),
              maximum_displacement=float(np.linalg.norm(delta, axis=1).max()),
              fine_hair_strands=strand_count,strand_vertices=len(strand_vertices),
              hair_vertices_removed_from_arm_bindings=hair_arm_bindings,
              materials={entry.name:categories.count(i) for i, entry in enumerate(materials)},
              preserved=['humanoid skin weights', 'portrait UVs', 'all facial morph targets'])
(WORK / 'polish-provenance.json').write_text(json.dumps(record, indent=2) + '\n')
print('CUSTOM_AVATAR_POLISHED', json.dumps(record), flush=True)
