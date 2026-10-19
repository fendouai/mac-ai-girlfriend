"""Derive a motion base from the author's demonstration, then remove recorded lip motion.

This is derived demonstration footage, not the missing original avatar source pack.
The runtime continues to use the original Wav2Lip weights for new spoken content.
"""
from pathlib import Path
import argparse,hashlib,json,os,pickle,sys
import av,cv2,numpy as np,torch

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',type=Path,default=ROOT/'models/avatar_sources/author-intro-4k.mp4')
parser.add_argument('--start',type=float,default=6.)
parser.add_argument('--duration',type=float,default=6.)
parser.add_argument('--avatar-id',default='hex_original_motion')
args=parser.parse_args()
args.source=args.source.expanduser().resolve()
if args.start < 0 or args.duration <= 0:raise SystemExit('Start must be non-negative and duration positive')
if not args.source.is_file():raise SystemExit('Download the author demonstration clip first; see README_MAC.md')
if not args.avatar_id.replace('_','').replace('-','').isalnum():raise SystemExit('Invalid avatar ID')
LT=ROOT/'third_party/livetalking';sys.path.insert(0,str(LT));os.chdir(LT)
torch.set_num_threads(4)
from avatars.wav2lip import face_detection,audio
from avatars.wav2lip.genavatar import get_smoothened_boxes
from avatars.wav2lip_avatar import load_model,CoreMLWav2Lip,LipReal

output=LT/'data/avatars'/args.avatar_id
raw=ROOT/'models/avatar_sources'/f'{args.avatar_id}-raw'
for p in [raw,output/'full_imgs',output/'face_imgs']:p.mkdir(parents=True,exist_ok=True)
# S3FD's bundled detector accepts CPU/CUDA only; this offline step runs once.
device='cpu'
detector=face_detection.FaceAlignment(face_detection.LandmarksType._2D,flip_input=False,device=device)
count=round(args.duration*25);next_time=args.start;boxes=[]
for frame in av.open(str(args.source)).decode(video=0):
    if frame.time is None or float(frame.time)<next_time-1e-5:continue
    if len(boxes)>=count:break
    image=frame.to_ndarray(format='bgr24')
    # The creator's browser layout reserves the rightmost 55% for the avatar.
    image=image[:,round(image.shape[1]*.45):].copy()
    scale=640/max(image.shape[:2]);small=cv2.resize(image,None,fx=scale,fy=scale)
    box=detector.get_detections_for_batch(small[None])[0]
    if box is None:raise RuntimeError(f'No face at source time {frame.time}')
    x1,y1,x2,y2=np.rint(np.asarray(box)/scale).astype(int)
    boxes.append([max(0,x1),max(0,y1),min(image.shape[1],x2),min(image.shape[0],y2+10)])
    cv2.imwrite(str(raw/f'{len(boxes)-1:08d}.png'),image,[cv2.IMWRITE_PNG_COMPRESSION,1])
    next_time=args.start+len(boxes)/25
    if len(boxes)%25==0:print('Detected source frames',len(boxes),'/',count,flush=True)
assert len(boxes)==count,(len(boxes),count)
del detector
if torch.backends.mps.is_available():torch.mps.empty_cache()
boxes=get_smoothened_boxes(np.asarray(boxes),T=5)
model=load_model(str(LT/'models/wav2lip.pth'))
assert isinstance(model,CoreMLWav2Lip),'Prepare the original Wav2Lip Core ML package first'
silence=audio.melspectrogram(np.zeros(16000,dtype=np.float32))[:,:16]
coords=[]
for first in range(0,count,4):
    frames=[cv2.imread(str(raw/f'{i:08d}.png')) for i in range(first,min(first+4,count))]
    batch_boxes=boxes[first:first+len(frames)]
    faces=[cv2.resize(im[y1:y2,x1:x2],(256,256)) for im,(x1,y1,x2,y2) in zip(frames,batch_boxes)]
    while len(faces)<4:faces.append(faces[-1])
    faces=np.asarray(faces);masked=faces.copy();masked[:,128:]=0
    pixels=(np.concatenate((masked,faces),axis=3).astype(np.float32)/255).transpose(0,3,1,2)
    mel=np.repeat(silence[None,None],4,axis=0)
    predicted=model.predict(mel,pixels).transpose(0,2,3,1)*255
    compositor=LipReal.__new__(LipReal);compositor.frame_list_cycle=frames
    compositor.coord_list_cycle=[(y1,y2,x1,x2) for x1,y1,x2,y2 in batch_boxes]
    for j,(x1,y1,x2,y2) in enumerate(batch_boxes):
        # Offline silent-mel inference removes speech recorded in the demonstration.
        neutral=compositor.paste_back_frame(predicted[j],j)
        name=f'{first+j:08d}.png'
        cv2.imwrite(str(output/'full_imgs'/name),neutral,[cv2.IMWRITE_PNG_COMPRESSION,1])
        cv2.imwrite(str(output/'face_imgs'/name),cv2.resize(neutral[y1:y2,x1:x2],(256,256)))
        coords.append((int(y1),int(y2),int(x1),int(x2)))
    if first%24==0:print('Neutralized mouth frames',first+len(frames),'/',count,flush=True)
with (output/'coords.pkl').open('wb') as f:pickle.dump(coords,f)
metadata={'type':'derived-author-demonstration-motion','source_url':'https://www.youtube.com/watch?v=xsh3UJ32p_w',
          'source_sha256':hashlib.sha256(args.source.read_bytes()).hexdigest(),
          'reference_image':'data/picture_1.png','reference_sha256':hashlib.sha256((ROOT/'data/picture_1.png').read_bytes()).hexdigest(),
          'start_seconds':args.start,'duration_seconds':args.duration,'fps':25,'frames':count,
          'crop':'rightmost 55% of author browser demonstration','mouth_cleanup':'original Wav2Lip silent mel; no source audio included',
          'limitations':'demonstration-derived crop, not the original raw avatar video or original avatar pack'}
(output/'source.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
print('Prepared author demonstration motion:',output,flush=True)
