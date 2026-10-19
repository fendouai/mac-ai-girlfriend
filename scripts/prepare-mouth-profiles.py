"""Prepare runtime mouth locations from previously measured source landmarks.

The MediaPipe measurements are an offline asset step. Runtime compositing needs
only the small published JSON, NumPy and OpenCV; it loads no landmark network.
"""
from pathlib import Path
import hashlib
import json

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'models/character3d-work'
profiles = {}
for name, filename in [('hex_clean_original', 'original-portrait-landmarks.json'),
                       ('hex_clean_sweet', 'portrait-landmarks.json')]:
    record = json.loads((WORK / filename).read_text())
    assert hashlib.sha256((ROOT / record['source']).read_bytes()).hexdigest() == record['source_sha256']
    points = np.array(record['landmarks'])[:, :2] * [768, 1024]
    left, right = points[[61, 291]]
    center = points[[13, 14]].mean(axis=0)
    profiles[name] = dict(center=(center / [768, 1024]).tolist(),
                          width=float(np.linalg.norm(right-left) / 768),
                          angle=float(np.arctan2(*(right-left)[::-1])),
                          nose_floor=float((points[2, 1]+3) / 1024),
                          reference=record['source'], reference_sha256=record['source_sha256'],
                          method='MediaPipe 478 facial landmarks; source pixels unchanged')
destination = ROOT / 'data/avatars/mouth-profiles.json'
destination.write_text(json.dumps(dict(version=1, avatars=profiles), indent=2) + '\n')
print('Prepared per-character mouth profiles:', ', '.join(profiles))
