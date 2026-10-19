"""Build a lip-sync avatar from the project's original README portrait (static body)."""
from pathlib import Path
import hashlib,json,pickle,sys
import cv2
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'data/picture_1.png'
image=cv2.imread(str(source))
assert image is not None
sys.path.insert(0,str(ROOT/'third_party/livetalking'))
from avatars.wav2lip import face_detection
detector=face_detection.FaceAlignment(face_detection.LandmarksType._2D,flip_input=False,device='cpu')
box=detector.get_detections_for_batch(image[None])[0]
assert box is not None, 'No face detected by original S3FD frontend'
x,y,x2,y2=map(int,box);w,h=x2-x,y2-y
scale=1.0
x1,y1=int(x*scale),int(y*scale);x2,y2=int((x+w)*scale),int((y+h+10)*scale)
folder=ROOT/'third_party/livetalking/data/avatars/hex_original'
for sub in ['full_imgs','face_imgs']:(folder/sub).mkdir(parents=True,exist_ok=True)
cv2.imwrite(str(folder/'full_imgs/00000000.png'),image)
cv2.imwrite(str(folder/'face_imgs/00000000.png'),cv2.resize(image[y1:y2,x1:x2],(256,256)))
with (folder/'coords.pkl').open('wb') as f:pickle.dump([(y1,y2,x1,x2)],f)
(folder/'source.json').write_text(json.dumps({'source':'data/picture_1.png','sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'type':'original project portrait with lip animation; static body'},indent=2))
print('Prepared original project portrait:',folder)
