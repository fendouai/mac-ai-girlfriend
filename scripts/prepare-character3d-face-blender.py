"""Blender: subdivide every measured expression consistently, then verify previews."""
from pathlib import Path
import json
import math
import bpy
from mathutils import Vector, kdtree

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'models/character3d-work'
record=json.loads((WORK/'face-basis.json').read_text())
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=str(WORK/'sweet-face-preview.glb'))
face=next(o for o in bpy.context.scene.objects if o.name.startswith('MeasuredFace'))
face.name='FaceSurface'
tree=kdtree.KDTree(len(record['vertices']))
for i,(x,y,z) in enumerate(record['vertices']):tree.insert(Vector((x,-z,y)),i)
tree.balance()
mapping=[]
for v in face.data.vertices:
    co,index,distance=tree.find(face.matrix_world@v.co)
    if distance>1e-5:raise RuntimeError('Facial vertex order cannot be matched to its measured basis')
    mapping.append(index)
face.shape_key_add(name='Basis')
for name,offsets in record['morphs'].items():
    key=face.shape_key_add(name=name)
    for vertex,index in zip(key.data,mapping):
        x,y,z=offsets[index];vertex.co+=Vector((x,-z,y))
sub=face.modifiers.new('Facial curvature','SUBSURF');sub.levels=2;sub.render_levels=2
sub.boundary_smooth='PRESERVE_CORNERS'
deps=bpy.context.evaluated_depsgraph_get();bpy.context.view_layer.update()
evaluated=face.evaluated_get(deps)
neutral=bpy.data.meshes.new_from_object(evaluated,preserve_all_data_layers=True,depsgraph=deps)
shapes={}
for name in record['morphs']:
    face.data.shape_keys.key_blocks[name].value=1
    bpy.context.view_layer.update();deps.update()
    current=face.evaluated_get(deps).to_mesh()
    if len(current.vertices)!=len(neutral.vertices):raise RuntimeError('Subdivision changed expression topology')
    shapes[name]=[v.co.copy() for v in current.vertices]
    face.evaluated_get(deps).to_mesh_clear()
    face.data.shape_keys.key_blocks[name].value=0
face.modifiers.clear();face.data=neutral
face.shape_key_add(name='Basis')
for name,coords in shapes.items():
    key=face.shape_key_add(name=name)
    for vertex,co in zip(key.data,coords):vertex.co=co
for polygon in face.data.polygons:polygon.use_smooth=True
head=[face]
for obj in bpy.context.scene.objects:
    if obj is face:continue
    if obj.name.startswith('Eye'):
        obj.name='Face'+obj.name;head.append(obj)
    elif obj.name.startswith('MouthInterior'):
        obj.name='FaceMouthInterior';head.append(obj)
for obj in head:
    for polygon in obj.data.polygons:polygon.use_smooth=True
# A shallow curved upper tooth row sits inside the oral volume, behind the lips.
# It becomes visible through the opening; the neutral photo remains closed-mouth.
points=[Vector(record['vertices'][i]) for i in record['mouth']]
lip=sum(points,Vector())/len(points)
tooth_material=bpy.data.materials.new('Natural enamel');tooth_material.diffuse_color=(.67,.63,.54,1)
for i in range(8):
    x=(i-3.5)*.0030
    y=lip.y-.0010
    z=lip.z-.0030-(abs(i-3.5)/3.5)**2*.002
    bpy.ops.mesh.primitive_cube_add(size=1,location=(lip.x+x,-z,y))
    tooth=bpy.context.object;tooth.name=f'FaceTooth{i}'
    tooth.scale=(.0028,.0018,.0033)
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    bevel=tooth.modifiers.new('Rounded enamel','BEVEL');bevel.width=.0006;bevel.segments=3
    bpy.context.view_layer.objects.active=tooth;bpy.ops.object.modifier_apply(modifier=bevel.name)
    tooth.data.materials.append(tooth_material);head.append(tooth)
bpy.ops.object.select_all(action='DESELECT')
for obj in head:obj.select_set(True)
bpy.context.view_layer.objects.active=face
bpy.ops.export_scene.gltf(filepath=str(WORK/'sweet-facial-rig.glb'),export_format='GLB',
                          use_selection=True,export_morph=True,export_animations=False)
bpy.ops.wm.save_as_mainfile(filepath=str(WORK/'sweet-facial-rig.blend'))
(WORK/'face-rig-provenance.json').write_text(json.dumps(dict(
    vertices=len(face.data.vertices),polygons=len(face.data.polygons),
    morphs=list(shapes),subdivision_levels=2,objects=[o.name for o in head],
    texture='GPT sweet-clean-v1.png portrait',topology='MediaPipe canonical face, Apache-2.0'),indent=2)+'\n')
# Render actual neutral, open-mouth and closed-eyelid geometry for visual checks.
scene=bpy.context.scene;scene.render.engine='BLENDER_EEVEE_NEXT'
scene.render.resolution_x=800;scene.render.resolution_y=1000;scene.render.resolution_percentage=100
scene.world.color=(.12,.12,.12)
target=Vector((0,-.06,.815))
for location,energy in [((-2,-4,3),700),((2,-3,2),350)]:
    bpy.ops.object.light_add(type='AREA',location=location);obj=bpy.context.object
    obj.data.energy=energy;obj.data.size=3
    obj.rotation_euler=(target-obj.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add(location=(0,-3,.815));camera=bpy.context.object
camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.type='ORTHO';camera.data.ortho_scale=.47;scene.camera=camera
for name in ['neutral','aa','blink']:
    if name!='neutral':face.data.shape_keys.key_blocks[name].value=1
    scene.render.filepath=str(ROOT/f'logs/character3d-face-{name}.png');bpy.ops.render.render(write_still=True)
    if name!='neutral':face.data.shape_keys.key_blocks[name].value=0
print('Facial morph export and three rendered states complete',flush=True)
