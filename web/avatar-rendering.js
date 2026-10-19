import * as THREE from 'three';

/** Local studio lighting: broad reflections, a neutral key and a gentle fill. */
export function configureAvatarRenderer(renderer, scene) {
  // Supersample standard-density panels too: subpixel hair and knit highlights
  // otherwise alias even though WebGL's edge MSAA is enabled.
  renderer.setPixelRatio(Math.min(2, Math.max(1.5, devicePixelRatio)));
  renderer.outputColorSpace=THREE.SRGBColorSpace;
  renderer.toneMapping=THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure=.92;
  renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFShadowMap;

  const studio=new THREE.Scene();
  studio.background=new THREE.Color(.08,.08,.09);
  const panel=(position,size,strength)=>{
    const mesh=new THREE.Mesh(new THREE.PlaneGeometry(...size),new THREE.MeshBasicMaterial({color:new THREE.Color(strength,strength,strength)}));
    mesh.position.set(...position);mesh.lookAt(0,1,0);studio.add(mesh);
  };
  panel([-3,3,3],[3,4],6);
  panel([3,2,2],[2,3],3);
  panel([0,4,-2],[3,2],5);
  const pmrem=new THREE.PMREMGenerator(renderer);
  const environment=pmrem.fromScene(studio,.025,.1,20);
  scene.environment=environment.texture;scene.environmentIntensity=.22;
  pmrem.dispose();
  studio.traverse(node=>{node.geometry?.dispose();node.material?.dispose();});

  scene.add(new THREE.HemisphereLight(0xfff7f0,0x687080,.5));
  for(const [color,power,position] of [
    [0xfff3e8,2.2,[-2,3,3]],
    [0xe8efff,.8,[2,1.5,3]],
    [0xffe9dd,.9,[-.5,2,-3]],
  ]) {
    const light=new THREE.DirectionalLight(color,power);light.position.set(...position);
    light.target.position.set(0,1,0);scene.add(light.target);scene.add(light);
    if(position[0]===-2) {
      light.castShadow=true;light.shadow.mapSize.set(1024,1024);light.shadow.radius=5;
      Object.assign(light.shadow.camera,{left:-1.35,right:1.35,top:1.35,bottom:-1.35,near:.1,far:10});
      light.shadow.bias=-.00015;light.shadow.normalBias=.003;
    }
  }
  return environment;
}

function knitNormalTexture() {
  const size=64,data=new Uint8Array(size*size*4);
  for(let y=0;y<size;y++)for(let x=0;x<size;x++) {
    const u=x/size*Math.PI*2,v=y/size*Math.PI*2;
    const dx=Math.sin(u)*(.65+.35*Math.cos(v));
    const dy=Math.sin(v)*(.65+.35*Math.cos(u));
    const normal=new THREE.Vector3(dx*.35,dy*.35,1).normalize(),i=(y*size+x)*4;
    data[i]=Math.round((normal.x*.5+.5)*255);data[i+1]=Math.round((normal.y*.5+.5)*255);data[i+2]=Math.round((normal.z*.5+.5)*255);data[i+3]=255;
  }
  const texture=new THREE.DataTexture(data,size,size);
  texture.wrapS=texture.wrapT=THREE.RepeatWrapping;texture.repeat.set(120,120);
  texture.magFilter=THREE.LinearFilter;texture.minFilter=THREE.LinearMipmapLinearFilter;
  texture.generateMipmaps=true;texture.needsUpdate=true;
  return texture;
}

export function refineAvatarMaterials(vrm, renderer) {
  const anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());
  const weave=knitNormalTexture();weave.anisotropy=anisotropy;
  const seen=new Set();
  vrm.scene.traverse(node=>{
    if(!node.isMesh)return;
    node.castShadow=node.name!=='AvatarFineHair';node.receiveShadow=true;
    for(const material of Array.isArray(node.material)?node.material:[node.material]) {
      if(!material||seen.has(material))continue;seen.add(material);
      for(const property of ['map','normalMap','roughnessMap'])if(material[property])material[property].anisotropy=anisotropy;
      if(material.name==='AvatarKnit') {
        material.normalMap=weave;material.normalScale.set(.18,.18);
      }
      if(material.name==='AvatarHair') {
        material.bumpMap=material.map;material.bumpScale=.001;
        material.roughness=.62;material.envMapIntensity=.25;
      }
      material.needsUpdate=true;
    }
  });
}

export function createContactShadow() {
  const canvas=document.createElement('canvas');canvas.width=canvas.height=128;
  const context=canvas.getContext('2d'),gradient=context.createRadialGradient(64,64,8,64,64,64);
  gradient.addColorStop(0,'rgba(20,15,23,.6)');gradient.addColorStop(.45,'rgba(20,15,23,.28)');gradient.addColorStop(1,'rgba(20,15,23,0)');
  context.fillStyle=gradient;context.fillRect(0,0,128,128);
  const texture=new THREE.CanvasTexture(canvas);
  const shadow=new THREE.Mesh(new THREE.PlaneGeometry(.9,.65),new THREE.MeshBasicMaterial({map:texture,transparent:true,depthWrite:false,opacity:.75}));
  shadow.rotation.x=-Math.PI/2;shadow.position.y=.003;
  return shadow;
}

export function createShadowFloor() {
  const floor=new THREE.Mesh(new THREE.PlaneGeometry(4,4),new THREE.ShadowMaterial({opacity:.16}));
  floor.rotation.x=-Math.PI/2;floor.position.y=.001;floor.receiveShadow=true;
  return floor;
}
