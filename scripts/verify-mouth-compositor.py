"""Check colour seams, preserved blinks and release/reset without model inference."""
from pathlib import Path
import json
import pickle
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'third_party/livetalking'))
from utils.mouth_compositor import MouthCompositor

profiles = json.loads((ROOT / 'data/avatars/mouth-profiles.json').read_text())['avatars']
for name, profile in profiles.items():
    folder = ROOT / 'third_party/livetalking/data/avatars' / name
    assert json.loads((folder / 'source.json').read_text())['reference_sha256'] == profile['reference_sha256']
    bbox = pickle.loads((folder / 'coords.pkl').read_bytes())[0]
    y1, y2, x1, x2 = bbox
    source = cv2.imread(str(folder / 'full_imgs/00000000.png'))
    compositor = MouthCompositor(profile)
    inner, outer, ring = compositor.masks(source.shape, bbox)
    prediction = np.clip(source[y1:y2, x1:x2].astype(float) + [9, 13, 17], 0, 255)
    times = []
    for _ in range(20):
        start = time.perf_counter()
        output = compositor.compose(source, prediction, bbox)
        times.append((time.perf_counter()-start)*1000)
    error = float(np.mean(np.abs(output[y1:y2, x1:x2].astype(float)-source[y1:y2, x1:x2])[ring]))
    assert error < .6, f'Constant illumination mismatch was not removed: {error}'
    outside = np.ones(source.shape[:2], bool)
    outside[y1:y2, x1:x2] = outer[..., 0] == 0
    assert np.array_equal(output[outside], source[outside]), 'Portrait pixels outside mouth changed'
    closed = cv2.imread(str(folder / 'full_imgs/00000059.png'))
    blink = compositor.compose(closed, prediction, bbox)
    assert np.array_equal(blink[:int(profile['nose_floor']*source.shape[0])],
                          closed[:int(profile['nose_floor']*source.shape[0])]), 'Natural blink or nose changed'
    # A genuinely changed lip must survive intact at the core after the attack.
    changed = prediction.copy()
    cy = int(profile['center'][1]*source.shape[0]-y1)
    cx = int(profile['center'][0]*source.shape[1]-x1)
    cv2.ellipse(changed, (cx, cy+5), (17, 11), 0, 0, 360, (35, 15, 20), -1)
    for _ in range(3):spoken = compositor.compose(source, changed, bbox)
    assert np.mean(abs(spoken[y1:y2,x1:x2].astype(float)-source[y1:y2,x1:x2])[inner[...,0]>.99]) > 2
    compositor.idle(source, bbox)
    assert np.array_equal(compositor.idle(source, bbox), source), 'Release did not return to the portrait'
    compositor.compose(source, changed, bbox)
    compositor.reset()
    assert compositor.idle(source, bbox) is source, 'Interrupt kept an old mouth frame'
    print(json.dumps(dict(avatar=name,passed=True,colour_ring_error=error,
                          mean_ms=float(np.mean(times)),p95_ms=float(np.percentile(times,95)))))
