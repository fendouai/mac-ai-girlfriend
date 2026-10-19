import {pathToFileURL} from 'node:url';
import {resolve as resolvePath} from 'node:path';
const root=resolvePath(import.meta.dirname,'..');
export async function resolve(specifier,context,nextResolve) {
  let file;
  if(specifier==='three')file='web/vendor/three/three.module.js';
  else if(specifier==='@pixiv/three-vrm')file='web/vendor/three-vrm.module.min.js';
  else if(specifier.startsWith('three/addons/'))file='web/vendor/three/'+specifier.slice(6);
  if(file)return {url:pathToFileURL(resolvePath(root,file)).href,shortCircuit:true};
  return nextResolve(specifier,context);
}
