"""Build original/sweet facial avatars from clean portraits, without demo footage.

Only eye regions use LivePortrait retargeting. Original mouth/body/background pixels
are retained; live spoken mouth motion still uses the original Wav2Lip model.
"""
from pathlib import Path
import sys,os,json,pickle,hashlib
import cv2,numpy as np,torch
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK','1')
sys.path.insert(0,str(ROOT/'third_party/LivePortrait'))
from src.config.inference_config import InferenceConfig
from src.config.crop_config import CropConfig
from src.live_portrait_wrapper import LivePortraitWrapper
from src.utils.cropper import Cropper
from src.utils.crop import paste_back
from src.utils.retargeting_utils import calc_eye_close_ratio

torch.set_num_threads(4)
wrapper=LivePortraitWrapper(InferenceConfig(flag_use_half_precision=False))
crop_cfg=CropConfig(flag_force_cpu=True)
cropper=Cropper(crop_cfg=crop_cfg,flag_force_cpu=True)
sys.path.insert(0,str(ROOT/'third_party/livetalking'))
from avatars.wav2lip import face_detection
sfd=face_detection.FaceAlignment(face_detection.LandmarksType._2D,flip_input=False,device='cpu')

for name,filename in [('hex_clean_original','original-clean-v1.png'),('hex_clean_sweet','sweet-clean-v1.png')]:
 source=ROOT/'data/avatars/generated'/filename
 output=ROOT/'third_party/livetalking/data/avatars'/name
 if (output/'source.json').exists():print('Already prepared',name,flush=True);continue
 image=cv2.cvtColor(cv2.resize(cv2.imread(str(source)),(768,1024)),cv2.COLOR_BGR2RGB)
 crop=cropper.crop_source_image(image,crop_cfg)
 assert crop is not None
 tensor=wrapper.prepare_source(crop['img_crop_256x256'])
 info=wrapper.get_kp_info(tensor);kp=wrapper.transform_keypoint(info);feature=wrapper.extract_feature_3d(tensor)
 landmarks=crop['lmk_crop'];ratio=float(calc_eye_close_ratio(landmarks[None]).mean())
 mask=np.zeros(image.shape[:2],np.float32)
 for points in (landmarks[:24],landmarks[24:48]):
  lo=points.min(0);hi=points.max(0);margin=(hi[0]-lo[0])*.3
  x1,y1=np.maximum(np.floor(lo-[margin,margin]),0).astype(int)
  x2,y2=np.minimum(np.ceil(hi+[margin,margin]),[image.shape[1]-1,image.shape[0]-1]).astype(int)
  cv2.ellipse(mask,((x1+x2)//2,(y1+y2)//2),((x2-x1)//2,(y2-y1)//2),0,0,360,1,-1)
 mask=cv2.GaussianBlur(mask,(21,21),4)[...,None]
 blink_frames={0:image.copy()}
 for amount in [.15,.5,.85,1.]:
  combined=wrapper.calc_combined_eye_ratio(np.array([[max(.015,ratio*(1-amount)),0]],np.float32),landmarks)
  delta=wrapper.retarget_eye(kp,combined)
  driving=wrapper.stitching(kp,kp+delta)
  result=wrapper.warp_decode(feature,kp,driving)
  face=wrapper.parse_output(result['out'])[0]
  reconstructed=paste_back(face,crop['M_c2o'],image,np.ones_like(image,np.float32))
  alpha=mask*min(1,amount*2)
  blink_frames[amount]=np.clip(image*(1-alpha)+reconstructed*alpha,0,255).astype(np.uint8)
  print(name,'prepared eye amount',amount,flush=True)
 bgr=cv2.cvtColor(image,cv2.COLOR_RGB2BGR)
 rect=sfd.get_detections_for_batch(bgr[None])[0];assert rect is not None
 x1,y1,x2,y2=map(int,rect);y2=min(y2+10,image.shape[0]);coord=(y1,y2,x1,x2)
 stage=output.with_name(output.name+'.preparing')
 for part in ['full_imgs','face_imgs']:(stage/part).mkdir(parents=True,exist_ok=True)
 curve=[0,.15,.5,.85,1.,.85,.5,.15,0]
 coords=[]
 saved_variants={}
 for index in range(200):
  amount=0
  for start in (55,151):
   if start<=index<start+len(curve):amount=curve[index-start]
  full=cv2.cvtColor(blink_frames[amount],cv2.COLOR_RGB2BGR)
  full_path=stage/'full_imgs'/f'{index:08d}.png';face_path=stage/'face_imgs'/f'{index:08d}.png'
  if amount in saved_variants:
   previous_full,previous_face=saved_variants[amount]
   os.link(previous_full,full_path);os.link(previous_face,face_path)
  else:
   cv2.imwrite(str(full_path),full,[cv2.IMWRITE_PNG_COMPRESSION,1])
   cv2.imwrite(str(face_path),cv2.resize(full[y1:y2,x1:x2],(256,256)))
   saved_variants[amount]=(full_path,face_path)
  coords.append(coord)
 with (stage/'coords.pkl').open('wb') as f:pickle.dump(coords,f)
 support=mask[...,0]>0
 outside=max(int(np.abs(value.astype(int)-image.astype(int))[~support].max()) for value in blink_frames.values())
 assert outside==0,'Pixels outside eye region changed'
 metadata={'type':'clean-generated-portrait-with-eye-retargeting','reference':str(source.relative_to(ROOT)),
  'reference_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'fps':25,'frames':200,
  'resolution':[768,1024],'facial_animation':'LivePortrait eye retargeting only; 0.32s blinks',
  'runtime_lip_sync':'original Wav2Lip256/Core ML','body_animation':False,
  'max_pixel_change_outside_eye_regions':outside,'source_footage':None}
 (stage/'source.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
 stage.rename(output)
 # Save neutral/half/closed eye references for visual inspection.
 (ROOT/'logs').mkdir(exist_ok=True)
 contact=np.concatenate([cv2.cvtColor(cv2.resize(blink_frames[a],(300,400)),cv2.COLOR_RGB2BGR) for a in (0,.5,1.)],axis=1)
 cv2.imwrite(str(ROOT/'logs'/f'{name}-eyes.jpg'),contact)
 print('Published facial avatar',output,flush=True)
