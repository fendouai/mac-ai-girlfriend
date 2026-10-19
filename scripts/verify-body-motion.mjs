/** Validate actual local VRM bones and the production motion retargeter, without rendering. */
import {register} from 'node:module';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import assert from 'node:assert/strict';
register(new URL('./node-avatar-loader.mjs',import.meta.url));
process.on('uncaughtException',error=>{console.error(error.message);console.error(error.stack?.split('\n').slice(1,5).join('\n'));process.exit(1);});
const THREE=await import('three');
const {GLTFLoader}=await import('three/addons/loaders/GLTFLoader.js');
const {VRMLoaderPlugin}=await import('@pixiv/three-vrm');
const {BodyAvatar}=await import('../web/body-avatar.js');
globalThis.window=new EventTarget();
globalThis.self=globalThis;
const root=resolve(import.meta.dirname,'..');
const path=resolve(process.argv[2]||root+'/web/assets/models/sweet-realistic.vrm');
const bytes=await readFile(path);
const loader=new GLTFLoader();
loader.register(parser=>new VRMLoaderPlugin(parser));
// GPU materials do not affect skeletal math. Keep this local asset test offline.
loader.register(()=>({name:'LocalSkeletonTest',loadTexture:()=>Promise.resolve(new THREE.DataTexture(new Uint8Array([255,255,255,255]),1,1))}));
const gltf=await loader.parseAsync(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'');
const avatar=new BodyAvatar({getBoundingClientRect:()=>({left:0,top:0,width:800,height:1000})});
avatar.vrm=gltf.userData.vrm;avatar.motionClips=JSON.parse(await readFile(root+'/web/assets/motions/conversation.json','utf8')).clips;
avatar.basePositions=new Map();avatar.baseWorld=new Map();
for(const name of Object.keys(avatar.vrm.humanoid.humanBones)){
  const node=avatar.vrm.humanoid.getNormalizedBoneNode(name);
  if(node){avatar.bones.set(name,node);avatar.base.set(name,node.quaternion.clone());avatar.basePositions.set(name,node.position.clone());}
}
avatar.vrm.scene.updateMatrixWorld(true);
for(const [name,node] of avatar.bones)avatar.baseWorld.set(name,node.getWorldQuaternion(new THREE.Quaternion()));
const depth=node=>{let n=0;while(node.parent){n++;node=node.parent;}return n;};
avatar.boneOrder=[...avatar.bones.keys()].sort((a,b)=>depth(avatar.bones.get(a))-depth(avatar.bones.get(b)));
const position=name=>avatar.bones.get(name).getWorldPosition(new THREE.Vector3());
avatar.restFootY=Math.min(position('leftFoot').y,position('rightFoot').y);
avatar.hipHeight=position('hips').y-avatar.restFootY;
const reset=()=>{for(const [name,node] of avatar.bones){node.quaternion.copy(avatar.base.get(name));node.position.copy(avatar.basePositions.get(name));}avatar.vrm.scene.updateMatrixWorld(true);};
let highest=-Infinity,lowest=Infinity;
for(let time=0;time<3.5;time+=.1){reset();avatar.applyMotionClip('wave',time,1);highest=Math.max(highest,position('rightHand').y);lowest=Math.min(lowest,position('rightHand').y);}
const height=position('head').y-avatar.restFootY;
assert(highest>avatar.restFootY+height*.85,'Waving hand never reaches the head');
assert(highest-lowest>height*.25,'Wave has insufficient real hand movement');
reset();avatar.applyMotionClip('walk',1,1);const walkA=position('leftFoot').distanceTo(position('rightFoot'));
reset();avatar.applyMotionClip('walk',2,1);const walkB=position('leftFoot').distanceTo(position('rightFoot'));
assert(Math.max(walkA,walkB)>height*.08,'Walk does not move the real legs');
for(const [name,node] of avatar.bones)assert(Math.abs(node.quaternion.length()-1)<1e-5,`${name}: quaternion drift`);
// Exercise the complete production pose update, including body-proportion IK.
avatar.height=new THREE.Box3().setFromObject(avatar.vrm.scene).getSize(new THREE.Vector3()).y;
avatar.action='wave';avatar.actionStart=0;
for(let frame=0;frame<90;frame++){
  avatar.elapsed=frame/60;avatar.updatePose(1/60);avatar.vrm.update(1/60);
}
const clearance=Math.abs(position('leftHand').x-position('hips').x);
assert(clearance>avatar.height*.14,'Resting hand intersects the hip/thigh during wave');
// Check that the production blink reaches the actual rendered mesh, rather than
// merely updating a requested expression value on the manager.
avatar.action=null;avatar.nextBlink=10;avatar.elapsed=10;
avatar.updatePose(1/60);avatar.elapsed=10.09;
avatar.updatePose(1/60);avatar.vrm.update(1/60);
let actualBlink=0;
avatar.vrm.scene.traverse(node=>{
  const index=node.morphTargetDictionary?.blink;
  if(index!==undefined)actualBlink=Math.max(actualBlink,node.morphTargetInfluences[index]);
});
assert(actualBlink>.95,'Blink never reaches the actual facial mesh');
console.log(JSON.stringify({model:path,bones:avatar.bones.size,wave:{highest,lowest,span:highest-lowest},walk:{footSeparation:[walkA,walkB]},actualBlink,passed:true},null,2));
