"""Measure facial landmarks in the generated source; no image pixels are edited."""
from pathlib import Path
import hashlib
import json
import argparse
import numpy as np
from PIL import Image
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'models/character3d-work'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, default=ROOT / 'data/avatars/generated/sweet-3d-front-v1.png')
parser.add_argument('--output', type=Path, default=WORK / 'face-landmarks.json')
parser.add_argument('--full-frame', action='store_true')
args = parser.parse_args()
source = args.source.resolve()
im = Image.open(source).convert('RGB')
width, height = im.size
box = (0, 0, width, height) if args.full_frame else (int(width*.3), 0, int(width*.7), int(height*.28))
crop = np.asarray(im.crop(box))
options = vision.FaceLandmarkerOptions(
    base_options=python.BaseOptions(model_asset_path=str(WORK/'face_landmarker.task')),
    running_mode=vision.RunningMode.IMAGE, num_faces=1,
    output_face_blendshapes=True, output_facial_transformation_matrixes=True)
with vision.FaceLandmarker.create_from_options(options) as detector:
    result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(crop)))
if len(result.face_landmarks) != 1:
    raise RuntimeError('Expected exactly one detected face in the modeling source')
landmarks = [[(p.x*crop.shape[1]+box[0])/width,
              (p.y*crop.shape[0]+box[1])/height, p.z*crop.shape[1]/width]
             for p in result.face_landmarks[0]]
record = dict(source=str(source.relative_to(ROOT)), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
              width=width, height=height, landmarks=landmarks,
              blendshapes={x.category_name:x.score for x in result.face_blendshapes[0]},
              transform=result.facial_transformation_matrixes[0].tolist(),
              method='MediaPipe FaceLandmarker, original GPT source pixels')
args.output.write_text(json.dumps(record,indent=2)+'\n')
print('Measured',len(landmarks),'facial points; mouth and eye boundaries available',flush=True)
