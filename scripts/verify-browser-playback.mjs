// Exercise the actual AudioWorklet resampler/queue used by the 3D presentation.
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const code=readFileSync(new URL('../web/worklets/audio-playback.js',import.meta.url),'utf8');
for(const rate of [16000,44100,48000]) {
 let Processor;
 const context=vm.createContext({sampleRate:rate,Float32Array,registerProcessor:(_,value)=>Processor=value,
  AudioWorkletProcessor:class {constructor(){this.port={postMessage(){},onmessage:null};}}});
 vm.runInContext(code,context);
 const processor=new Processor();
 processor.port.onmessage({data:{kind:'config',inputRate:16000,delayMs:0}});
 const tone=Float32Array.from({length:16000*8},(_,i)=>.2*Math.sin(i*2*Math.PI*220/16000));
 // Whole replies and chunk boundaries must both play continuously.
 for(let i=0;i<tone.length;i+=1379)processor.port.onmessage({data:{kind:'audio',samples:tone.slice(i,i+1379)}});
 const energy=[];
 for(let i=0;i<Math.ceil(rate*8.1/128);i++){
  const block=new Float32Array(128);processor.process([],[[block]]);
  energy.push(Math.sqrt(block.reduce((n,x)=>n+x*x,0)/block.length));
 }
 const active=energy.flatMap((e,i)=>e>.01?[i]:[]);
 const first=active[0],last=active.at(-1);
 assert.ok(first!==undefined);
 assert.ok(Math.abs((last-first+1)*128/rate-8)<.02);
 assert.equal(energy.slice(first,last+1).filter(e=>e<.01).length,0);
 processor.port.onmessage({data:{kind:'audio',samples:tone}});
 processor.process([],[[new Float32Array(128)]]);
 processor.port.onmessage({data:{kind:'clear'}});
 for(let i=0;i<10;i++)processor.process([],[[new Float32Array(128)]]);
 const silent=new Float32Array(128);processor.process([],[[silent]]);
 assert.ok(silent.every(x=>Math.abs(x)<1e-4),'Interrupted audio continued');
 console.log(`PASS: browser audio ${rate}Hz; 8s continuous; no inserted silent blocks; interruption clears queue`);
}
