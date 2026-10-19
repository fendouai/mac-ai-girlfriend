"""Convert the original Wav2Lip256 checkpoint to an Apple Core ML program."""
from pathlib import Path
import sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'third_party/livetalking'))
import torch,numpy as np,coremltools as ct
from avatars.wav2lip.models import Wav2Lip
batch=4
model=Wav2Lip().eval()
state=torch.load(ROOT/'third_party/livetalking/models/wav2lip.pth',map_location='cpu',weights_only=True)['state_dict']
model.load_state_dict({k.replace('module.',''):v for k,v in state.items()})
audio=torch.randn(batch,1,80,16);face=torch.rand(batch,6,256,256)
with torch.no_grad():
 reference=model(audio,face).numpy()
 traced=torch.jit.trace(model,(audio,face))
converted=ct.convert(traced,convert_to='mlprogram',minimum_deployment_target=ct.target.macOS13,
 inputs=[ct.TensorType(name='mel',shape=audio.shape),ct.TensorType(name='face',shape=face.shape)],
 outputs=[ct.TensorType(name='prediction')],compute_precision=ct.precision.FLOAT16,
 compute_units=ct.ComputeUnit.ALL)
path=ROOT/'models/wav2lip256-b4.mlpackage';converted.save(str(path))
print('Saved',path,flush=True)
for units in [ct.ComputeUnit.ALL,ct.ComputeUnit.CPU_AND_GPU]:
 m=ct.models.MLModel(str(path),compute_units=units)
 timings=[]
 for i in range(6):
  t=time.perf_counter();out=m.predict({'mel':audio.numpy(),'face':face.numpy()})['prediction'];timings.append(time.perf_counter()-t)
 print('units',units,'fps',batch/(sum(timings[2:])/4),'mean absolute error',np.abs(reference-out).mean(),'max error',np.abs(reference-out).max(),flush=True)
