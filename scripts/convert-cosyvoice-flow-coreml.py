"""Convert the original CosyVoice2 flow estimator for Apple Core ML acceleration."""
import os,sys,time
from pathlib import Path
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'third_party/CosyVoice'))
import torch,numpy as np,coremltools as ct
from hyperpyyaml import load_hyperpyyaml
root=ROOT/'models/CosyVoice2-0.5B'
with (root/'cosyvoice2.yaml').open() as f:cfg=load_hyperpyyaml(f,overrides={'qwen_pretrain_path':str(root/'CosyVoice-BlankEN')})
flow=cfg['flow'];flow.load_state_dict(torch.load(root/'flow.pt',map_location='cpu',weights_only=True));flow.eval()
class Wrapper(torch.nn.Module):
 def __init__(self,model):super().__init__();self.estimator=model
 def forward(self,x,mask,mu,t,spks,cond):return self.estimator(x,mask,mu,t,spks,cond,streaming=False)
m=Wrapper(flow.decoder.estimator).eval();del cfg,flow
torch.set_num_threads(4)
length=1024
args=(torch.randn(2,80,length),torch.ones(2,1,length),torch.randn(2,80,length),torch.ones(2)*.5,torch.randn(2,80),torch.randn(2,80,length))
with torch.inference_mode():
 reference=m(*args).numpy();print('Reference evaluated',flush=True)
 traced=torch.jit.trace(m,args,check_trace=False);print('Traced',flush=True)
converted=ct.convert(traced,convert_to='mlprogram',minimum_deployment_target=ct.target.macOS13,
 inputs=[ct.TensorType(name=n,shape=tuple(a.shape[:-1])+(ct.RangeDim(lower_bound=32, upper_bound=2048, default=1024),) if n in ('x','mask','mu','cond') else a.shape) for n,a in zip(['x','mask','mu','t','spks','cond'],args)],
 outputs=[ct.TensorType(name='prediction')],compute_precision=ct.precision.FLOAT16,compute_units=ct.ComputeUnit.CPU_AND_GPU)
path=ROOT/'models/cosyvoice2-flow.mlpackage';converted.save(str(path));print('Saved',path,flush=True)
inputs={n:a.numpy() for n,a in zip(['x','mask','mu','t','spks','cond'],args)}
for units in [ct.ComputeUnit.CPU_AND_GPU]:
 model=ct.models.MLModel(str(path),compute_units=units);times=[]
 for i in range(4):
  t=time.perf_counter();out=model.predict(inputs)['prediction'];times.append(time.perf_counter()-t)
 print(units,'seconds',sum(times[1:])/3,'MAE',np.abs(out-reference).mean(),'max',np.abs(out-reference).max(),flush=True)

short_args=tuple(a[:,:,:640] if a.ndim==3 else a for a in args)
with torch.inference_mode():expected=m(*short_args).numpy()
inputs={n:a.numpy() for n,a in zip(['x','mask','mu','t','spks','cond'],short_args)}
model=ct.models.MLModel(str(path),compute_units=ct.ComputeUnit.CPU_AND_GPU)
out=model.predict(inputs)['prediction']
print('dynamic length 640 shape',out.shape,'MAE',np.abs(out-expected).mean(),flush=True)
