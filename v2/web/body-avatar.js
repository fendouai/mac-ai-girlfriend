import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin } from '@pixiv/three-vrm';
import { configureAvatarRenderer, refineAvatarMaterials, createContactShadow, createShadowFloor } from './avatar-rendering.js?v=polish-5';

const clamp = THREE.MathUtils.clamp;
const smooth = (x) => { x=clamp(x,0,1); return x*x*(3-2*x); };
const ACTIONS = { wave:3.7, nod:1.8, think:4, explain:3.5, bow:2.6, happy:3.7, walk:4.7, dance:5.7 };

/** A real humanoid rig: all gestures operate on normalized VRM bones. */
export class BodyAvatar {
  constructor(layer) {
    this.layer=layer; this.vrm=null; this.active=false; this.ready=false;
    this.action=null; this.actionStart=0; this.mouth=0; this.mood='relaxed';
    this.status='idle'; this.lastResponse=''; this.emotions={happy:0,sad:0,relaxed:0}; this.analyser=null; this.audioContext=null;
    this.base=new Map(); this.bones=new Map(); this.previousPose=new Map(); this.frames=0; this.lastRms=0; this.speechFrames=0; this.peakMouth=0; this.peakRms=0; this.actionCounts={};
    this.clock=new THREE.Clock(); this.elapsed=0; this.nextBlink=3; this.blinkStart=-10;
    this.pointer=new THREE.Vector2(); this.pose={}; this.renderMs=0;
    this.onPointer=(event)=>{
      const rect=this.layer.getBoundingClientRect();
      this.pointer.set(clamp((event.clientX-rect.left)/rect.width*2-1,-1,1),clamp((event.clientY-rect.top)/rect.height*2-1,-1,1));
    };
    window.addEventListener('pointermove',this.onPointer);
  }
  async load() {
    if(this.loading) return this.loading;
    this.loading=this.loadModel(); return this.loading;
  }
  async loadModel() {
    this.renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,powerPreference:'high-performance'});
    this.renderer.domElement.id='body-canvas';
    this.renderer.domElement.setAttribute('aria-label','可做全身动作的 3D 人物');
    this.layer.appendChild(this.renderer.domElement);
    this.scene=new THREE.Scene(); this.camera=new THREE.PerspectiveCamera(30,1,.01,100);
    this.environment=configureAvatarRenderer(this.renderer,this.scene);
    const loader=new GLTFLoader();loader.register(parser=>new VRMLoaderPlugin(parser));
    const [gltf,motionData]=await Promise.all([
      loader.loadAsync('/assets/models/sweet-realistic.vrm?v=polish-5'),
      fetch('/assets/motions/conversation.json').then(response=>{
        if(!response.ok)throw new Error('无法加载本地全身动作');return response.json();
      }),
    ]);
    this.motionClips=motionData.clips;
    this.vrm=gltf.userData.vrm;this.scene.add(this.vrm.scene);
    refineAvatarMaterials(this.vrm,this.renderer);
    for(const name of Object.keys(this.vrm.humanoid.humanBones)) {
      const node=this.vrm.humanoid.getNormalizedBoneNode(name);
      if(node) {this.bones.set(name,node);this.base.set(name,node.quaternion.clone());}
    }
    this.vrm.scene.updateMatrixWorld(true);
    this.basePositions=new Map();this.baseWorld=new Map();
    const depth=node=>{let n=0;while(node.parent){n++;node=node.parent;}return n;};
    this.boneOrder=[...this.bones.keys()].sort((a,b)=>depth(this.bones.get(a))-depth(this.bones.get(b)));
    for(const [name,node] of this.bones){this.basePositions.set(name,node.position.clone());this.baseWorld.set(name,node.getWorldQuaternion(new THREE.Quaternion()));}
    const bounds=new THREE.Box3().setFromObject(this.vrm.scene);this.height=bounds.max.y-bounds.min.y;
    this.vrm.scene.position.y-=bounds.min.y;
    this.vrm.scene.updateMatrixWorld(true);
    const restFeet=['leftFoot','rightFoot'].map(name=>this.bones.get(name)?.getWorldPosition(new THREE.Vector3()).y).filter(Number.isFinite);
    this.restFootY=Math.min(...restFeet);
    this.hipHeight=this.bones.get('hips').getWorldPosition(new THREE.Vector3()).y-this.restFootY;
    this.camera.position.set(0,this.height*.54,this.height*2.2);
    this.camera.lookAt(0,this.height*.51,0);
    this.scene.add(createContactShadow());
    this.scene.add(createShadowFloor());
    this.observer=new ResizeObserver(()=>this.resize());this.observer.observe(this.layer);this.resize();
    this.ready=true;this.loop();
    return this;
  }
  resize() {
    const rect=this.layer.getBoundingClientRect();if(!rect.width||!rect.height)return;
    this.renderer.setSize(rect.width,rect.height,false);this.camera.aspect=rect.width/rect.height;this.camera.updateProjectionMatrix();
  }
  async show() {await this.load();this.active=true;this.layer.classList.add('body-live','live');this.renderer.domElement.hidden=false;}
  hide() {this.active=false;this.layer.classList.remove('body-live');if(this.renderer)this.renderer.domElement.hidden=true;this.interrupt();}
  setAudio(analyser,ctx) {this.analyser=analyser;this.audioContext=ctx;this.waveform=new Float32Array(analyser?.fftSize||1024);this.spectrum=new Float32Array(analyser?.frequencyBinCount||512);}
  setStatus(status) {this.status=status;if(status==='user-speaking')this.interrupt();}
  interrupt() {this.action=null;this.mouth=0;this.lastResponse='';this.lastRms=0;}
  gesture(name) {
    if(!ACTIONS[name])return false;
    this.action=name;this.actionStart=this.elapsed;this.actionCounts[name]=(this.actionCounts[name]||0)+1;
    window.dispatchEvent(new CustomEvent('body-action',{detail:{name}}));return true;
  }
  react({role,text,responseId,partial}) {
    if(!text)return;
    if(role==='user'&&!partial) {
      if(/停止动作|别动/.test(text)) {this.action=null;return;}
      const command=/挥手|招手/.test(text)?'wave':/点头/.test(text)?'nod':/鞠躬/.test(text)?'bow':/思考/.test(text)?'think':/跳舞/.test(text)?'dance':/走两步|走动|走路|散步/.test(text)?'walk':null;
      if(command){this.gesture(command);this.userGestureUntil=this.elapsed+ACTIONS[command];}
      return;
    }
    if(role!=='assistant'||text.length<4)return;
    const key=responseId||text;
    if(this.lastResponse===key)return;
    this.lastResponse=key;
    this.mood=/难过|抱歉|伤心|对不起/.test(text)?'sad':/开心|喜欢|高兴|好呀|哈哈|你好/.test(text)?'happy':'relaxed';
    if(this.elapsed<(this.userGestureUntil||0))return;
    if(/你好|欢迎|回来|再见|拜拜|挥手|招手/.test(text))this.gesture('wave');
    else if(/谢谢|感谢|不好意思|抱歉/.test(text))this.gesture('bow');
    else if(/想想|思考|觉得|为什么|让我想/.test(text))this.gesture('think');
    else if(/对的|没错|当然|可以|好的/.test(text))this.gesture('nod');
    else this.gesture('explain');
  }
  bone(name,x=0,y=0,z=0) {
    const node=this.bones.get(name);if(!node)return;
    node.quaternion.copy(this.base.get(name)).multiply(new THREE.Quaternion().setFromEuler(new THREE.Euler(x,y,z)));
    this.pose[name]=[x,y,z];
  }
  solveArmIK(side, target, amount) {
    const upper=this.bones.get(side+'UpperArm'),lower=this.bones.get(side+'LowerArm'),hand=this.bones.get(side+'Hand');
    if(!upper||!lower||!hand)return;
    this.vrm.scene.updateMatrixWorld(true);
    const shoulder=upper.getWorldPosition(new THREE.Vector3());
    const elbow=lower.getWorldPosition(new THREE.Vector3());
    const wrist=hand.getWorldPosition(new THREE.Vector3());
    target=wrist.clone().lerp(target,amount);
    const l1=shoulder.distanceTo(elbow),l2=elbow.distanceTo(wrist);
    const axis=target.clone().sub(shoulder),d=clamp(axis.length(),.02,l1+l2-.005);axis.normalize();
    const a=(l1*l1-l2*l2+d*d)/(2*d),h=Math.sqrt(Math.max(0,l1*l1-a*a));
    const bend=new THREE.Vector3(side==='right'?-.4:.4,-1,.12);
    bend.addScaledVector(axis,-bend.dot(axis)).normalize();
    const desiredElbow=shoulder.clone().addScaledVector(axis,a).addScaledVector(bend,h);
    const rotateTo=(node,from,to)=>{
      const delta=new THREE.Quaternion().setFromUnitVectors(from.normalize(),to.normalize());
      const world=node.getWorldQuaternion(new THREE.Quaternion()).premultiply(delta);
      const parent=node.parent.getWorldQuaternion(new THREE.Quaternion()).invert();
      node.quaternion.copy(parent.multiply(world));node.updateMatrixWorld(true);
    };
    rotateTo(upper,elbow.clone().sub(shoulder),desiredElbow.clone().sub(shoulder));
    this.vrm.scene.updateMatrixWorld(true);
    const newElbow=lower.getWorldPosition(new THREE.Vector3());
    const newWrist=hand.getWorldPosition(new THREE.Vector3());
    rotateTo(lower,newWrist.sub(newElbow),target.clone().sub(newElbow));
  }
  applyMotionClip(name, time, amount) {
    const clip=this.motionClips?.[name];if(!clip||amount<=0)return;
    const position=clamp((time-.35)*clip.fps,0,clip.quaternions.length-1);
    const a=Math.floor(position),b=Math.min(a+1,clip.quaternions.length-1),blend=position-a;
    const lookup=new Map(clip.bones.map((bone,index)=>[bone,index]));
    this.vrm.scene.updateMatrixWorld(true);
    const baseline=new Map([...this.bones].map(([bone,node])=>[bone,node.getWorldQuaternion(new THREE.Quaternion())]));
    for(const bone of this.boneOrder) {
      const index=lookup.get(bone);if(index===undefined)continue;
      const node=this.bones.get(bone);
      const motion=new THREE.Quaternion().fromArray(clip.quaternions[a][index]);
      motion.slerp(new THREE.Quaternion().fromArray(clip.quaternions[b][index]),blend);
      const desired=motion.multiply(this.baseWorld.get(bone));
      const world=baseline.get(bone).slerp(desired,amount);
      const parent=node.parent.getWorldQuaternion(new THREE.Quaternion()).invert();
      node.quaternion.copy(parent.multiply(world));node.updateMatrixWorld(true);
    }
    const hips=this.bones.get('hips'),scale=this.hipHeight/clip.hipHeight;
    const delta=clip.hips[a].map((value,index)=>THREE.MathUtils.lerp(value,clip.hips[b][index],blend));
    hips.position.y+=delta[1]*scale*amount;
    if(name!=='walk') {
      hips.position.x+=clamp(delta[0]*scale,-.10,.10)*amount;
      hips.position.z+=clamp(delta[2]*scale,-.10,.10)*amount;
    }
    this.motionClip=name;
  }
  updatePose(dt) {
    const t=this.elapsed;
    for(const [name,node] of this.bones)node.quaternion.copy(this.base.get(name));
    for(const [name,node] of this.bones)node.position.copy(this.basePositions.get(name));
    this.motionClip=null;
    this.pose={};
    const idle=Math.sin(t*1.1);
    const speaking=this.lastRms>.008;
    this.bone('leftUpperArm',.02,0,-1.22);this.bone('rightUpperArm',.02,0,1.22);
    this.bone('leftLowerArm',0,-.08,-.08);this.bone('rightLowerArm',0,.08,.08);
    this.bone('spine',.012*idle,.012*Math.sin(t*.46),.012*Math.sin(t*.63));
    this.bone('chest',.01*idle,0,.007*Math.sin(t*.63));
    this.bone('head',this.pointer.y*.035+.012*Math.sin(t*.77),this.pointer.x*.075,.012*Math.sin(t*.57));
    this.bone('hips',0,.012*Math.sin(t*.63),.009*Math.sin(t*.63));
    let envelope=0;
    if(this.action) {
      const u=t-this.actionStart,duration=ACTIONS[this.action];
      envelope=smooth(u/.65)*smooth((duration-u)/.7);
      if(u>=duration)this.action=null;
      const blend=(name,target)=>{const current=this.pose[name]||[0,0,0];this.bone(name,...current.map((v,i)=>v+(target[i]-v)*envelope));};
      if(this.action==='wave') {
        blend('rightUpperArm',[-.18,-.25,-.28]);blend('rightLowerArm',[0,-.1,-1.4]);
        blend('rightHand',[.12,Math.sin(u*7)*.25,-.15+Math.sin(u*7)*.25]);
      } else if(this.action==='think') {
        blend('head',[.05,-.12,.08]);
        this.vrm.scene.updateMatrixWorld(true);
        const chin=this.bones.get('head').getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(-.035,-.24,.17));
        this.solveArmIK('right',chin,envelope);
        for(const [finger,curl] of [['Index',.6],['Middle',.8],['Ring',1.0],['Little',1.1]]) {
          blend('right'+finger+'Proximal',[0,curl,0]);
          blend('right'+finger+'Intermediate',[0,.7,0]);
          blend('right'+finger+'Distal',[0,.4,0]);
        }
      } else if(this.action==='explain') {
        blend('leftUpperArm',[-.25,.15,-.85]);blend('leftLowerArm',[-.1,-.6,-.75]);blend('leftHand',[-.3,-.1,Math.sin(u*2)*.08]);
        blend('head',[.015*Math.sin(u*3),-.05,0]);
      } else if(this.action==='nod') {
        blend('head',[Math.sin(u*6)*.12,0,0]);
      } else if(this.action==='bow') {
        blend('hips',[.16,0,0]);blend('spine',[.12,0,0]);blend('head',[.13,0,0]);
        blend('leftUpperLeg',[-.08,0,0]);blend('rightUpperLeg',[-.08,0,0]);
        blend('leftLowerLeg',[.08,0,0]);blend('rightLowerLeg',[.08,0,0]);
      } else if(this.action==='happy') {
        blend('leftUpperArm',[-.2,0,-.5]);blend('rightUpperArm',[-.2,0,.5]);
        blend('leftLowerArm',[0,0,-1.65]);blend('rightLowerArm',[0,0,1.65]);
        blend('chest',[0,0,Math.sin(u*2.5)*.04]);
      }
      if(this.action&&this.motionClips?.[this.action])this.applyMotionClip(this.action,u,envelope);
    }
    // Adapt the recorded arms to this character's actual hip/torso proportions.
    // A clip authored on a thinner body can otherwise bury the resting hand in a leg.
    if(this.motionClip) {
      this.vrm.scene.updateMatrixWorld(true);
      const hips=this.bones.get('hips').getWorldPosition(new THREE.Vector3());
      for(const side of ['left','right']) {
        const hand=this.bones.get(side+'Hand').getWorldPosition(new THREE.Vector3());
        const offset=hand.clone().sub(hips),sign=side==='left'?1:-1;
        const belowShoulder=offset.y<this.height*.20&&offset.y>-this.height*.28;
        const clearance=this.height*.165;
        if(belowShoulder&&Math.abs(offset.z)<this.height*.13&&Math.abs(offset.x)<clearance) {
          const target=hand.clone();target.x=hips.x+sign*clearance;
          this.solveArmIK(side,target,1);
        }
      }
    }
    // Blend actual local bone quaternions across action replacements and stops.
    // This also smooths IK solutions; facial visemes stay on the audio clock.
    for(const [name,node] of this.bones) {
      const previous=this.previousPose.get(name);
      if(previous){previous.slerp(node.quaternion,1-Math.exp(-18*dt));node.quaternion.copy(previous);}
      else this.previousPose.set(name,node.quaternion.clone());
    }
    if(this.motionClip) {
      this.vrm.scene.updateMatrixWorld(true);
      const minimum=Math.min(...['leftFoot','rightFoot'].map(name=>this.bones.get(name).getWorldPosition(new THREE.Vector3()).y));
      this.bones.get('hips').position.y+=this.restFootY-minimum;
    }
    if(t>=this.nextBlink){this.blinkStart=t;this.nextBlink=t+3.4+Math.random()*3.0;}
    const blink=Math.max(0,1-Math.abs((t-this.blinkStart-.09)/.09));
    const manager=this.vrm.expressionManager;
    for(const name of ['happy','sad','relaxed']) {
      const target=name===this.mood?(name==='happy'?.3:.15):0;
      this.emotions[name]=THREE.MathUtils.damp(this.emotions[name],target,7,dt);
      manager.setValue(name,this.emotions[name]);
    }
    manager.setValue('blink',blink);
    let target=0,high=0,low=0;
    if(this.analyser&&this.audioContext?.state==='running') {
      this.analyser.getFloatTimeDomainData(this.waveform);this.analyser.getFloatFrequencyData(this.spectrum);
      let sum=0;for(const value of this.waveform)sum+=value*value;this.lastRms=Math.sqrt(sum/this.waveform.length);
      target=clamp((this.lastRms-.005)*8,0,.85);
      const step=this.audioContext.sampleRate/this.analyser.fftSize;
      for(let i=1;i<this.spectrum.length;i++){const frequency=i*step,power=10**(this.spectrum[i]/20);if(frequency<750)low+=power;else if(frequency<3000)high+=power;}
    } else this.lastRms=0;
    this.mouth=THREE.MathUtils.damp(this.mouth,target,target>this.mouth?24:32,dt);
    // Audio-driven shapes, not claimed to be a Mandarin phoneme aligner.
    if(this.mouth<.0001)this.mouth=0;
    if(this.lastRms>.008)this.speechFrames++;
    this.peakMouth=Math.max(this.peakMouth,this.mouth);this.peakRms=Math.max(this.peakRms,this.lastRms);
    const round=clamp(low/(low+high+.0001),0,1);
    manager.setValue('aa',this.mouth*(.65-.25*round));manager.setValue('oh',this.mouth*round*.5);manager.setValue('ih',this.mouth*(1-round)*.4);
    manager.setValue('ou',0);manager.setValue('ee',0);
  }
  loop() {
    this.raf=requestAnimationFrame(()=>this.loop());
    const dt=Math.min(this.clock.getDelta(),.05);this.elapsed+=dt;
    if(!this.active||!this.ready)return;
    const start=performance.now();this.updatePose(dt);this.vrm.update(dt);this.renderer.render(this.scene,this.camera);
    this.frames++;this.renderMs=performance.now()-start;
    const phase=this.action?this.elapsed-this.actionStart:0;
    this.renderer.domElement.dataset.action=this.action||'idle';
    this.renderer.domElement.dataset.mouthActive=String(this.mouth>.04);
    this.renderer.domElement.dataset.hasSpoken=String(this.speechFrames>0);
    this.renderer.domElement.dataset.blinkActive=String(this.vrm.expressionManager.getValue('blink')>.7);
    this.renderer.domElement.dataset.gesturePhase=this.action&&phase>.7&&phase<ACTIONS[this.action]-.75?'hold':'transition';
    if(this.frames%6===0) {
      this.renderer.domElement.dataset.rig=JSON.stringify(this.metrics());
    }
    const audible=this.lastRms>.008;
    if(audible) this.lastVoiceTime=this.elapsed;
    const activeSound=audible||(this.elapsed-(this.lastVoiceTime||-10)<.35);
    if(activeSound!==this.soundActive) {
      this.soundActive=activeSound;
      window.dispatchEvent(new CustomEvent('avatar-sound',{detail:{speaking:activeSound}}));
    }
  }
  metrics() {
    const morphs={};this.vrm.scene.traverse(node=>{
      if(!node.morphTargetDictionary||!node.morphTargetInfluences)return;
      for(const name of ['aa','oh','ih','blink','happy']) {
        const index=node.morphTargetDictionary[name];
        if(index!==undefined)morphs[name]=Math.max(morphs[name]||0,node.morphTargetInfluences[index]||0);
      }
    });
    this.peakMorphs||={};
    for(const [name,value] of Object.entries(morphs))this.peakMorphs[name]=Math.max(this.peakMorphs[name]||0,value);
    const world={};for(const name of ['head','rightHand','leftHand','leftFoot','rightFoot']){const node=this.bones.get(name);if(node)world[name]=node.getWorldPosition(new THREE.Vector3()).toArray();}
    const rotations={};for(const name of ['head','hips','rightUpperArm','rightLowerArm','leftUpperArm']){const node=this.bones.get(name);if(node)rotations[name]=node.quaternion.toArray();}
    return {ready:this.ready,active:this.active,frames:this.frames,bones:this.bones.size,action:this.action,motionClip:this.motionClip,pose:this.pose,world,rotations,morphs,peakMorphs:this.peakMorphs,mouth:this.mouth,rms:this.lastRms,peakMouth:this.peakMouth,peakRms:this.peakRms,speechFrames:this.speechFrames,actionCounts:this.actionCounts,renderMs:this.renderMs};
  }
}
