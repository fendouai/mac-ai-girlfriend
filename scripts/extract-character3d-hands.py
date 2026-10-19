"""Measure both source hands for fitting anatomically separate finger surfaces."""
from pathlib import Path
import hashlib
import json
import numpy as np
from PIL import Image
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'models/character3d-work'
source = ROOT / 'data/avatars/generated/sweet-3d-front-v1.png'
image = Image.open(source).convert('RGB')
w, h = image.size
options = vision.HandLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_path=str(WORK/'hand_landmarker.task')),
    running_mode=vision.RunningMode.IMAGE, num_hands=1,
    min_hand_detection_confidence=.35, min_hand_presence_confidence=.35)
hands = {}
with vision.HandLandmarker.create_from_options(options) as detector:
    for side, box in [('R', (0,int(h*.37),int(w*.34),int(h*.63))),
                      ('L', (int(w*.66),int(h*.37),w,int(h*.63)))]:
        crop = np.ascontiguousarray(np.asarray(image.crop(box)))
        result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=crop))
        if len(result.hand_landmarks) != 1:
            raise RuntimeError(f'Expected one {side} hand in source crop; found {len(result.hand_landmarks)}')
        hands[side] = dict(landmarks=[[(p.x*crop.shape[1]+box[0])/w,
                                        (p.y*crop.shape[0]+box[1])/h,
                                        p.z*crop.shape[1]/w]
                                       for p in result.hand_landmarks[0]],
                           score=result.handedness[0][0].score,
                           world=[[p.x,p.y,p.z] for p in result.hand_world_landmarks[0]])
record = dict(source=str(source.relative_to(ROOT)),
              source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), hands=hands)
(WORK/'hand-landmarks.json').write_text(json.dumps(record,indent=2)+'\n')
print('Measured both hands:', {k:dict(points=len(v['landmarks']), confidence=v['score']) for k,v in hands.items()},flush=True)
