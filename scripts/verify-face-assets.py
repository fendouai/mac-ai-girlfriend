"""Check both published face variants, including frozen body/background pixels."""
from pathlib import Path
import cv2,numpy as np,pickle
ROOT=Path(__file__).resolve().parents[1]
for name in ['hex_clean_original','hex_clean_sweet']:
    directory=ROOT/'third_party/livetalking/data/avatars'/name
    images=sorted((directory/'full_imgs').glob('*.png'))
    with (directory/'coords.pkl').open('rb') as handle:coords=pickle.load(handle)
    assert len(images)==len(coords)==200
    reference=cv2.imread(str(images[0]));y1,y2,x1,x2=coords[0]
    outside=np.ones(reference.shape[:2],bool);outside[y1:y2,x1:x2]=False
    changed=[]
    for index,file in enumerate(images):
        image=cv2.imread(str(file));assert image.shape==reference.shape
        difference=cv2.absdiff(image,reference)
        assert not np.any(difference[outside]),'Body/background moved in facial presentation'
        assert coords[index]==coords[0],'Face crop jittered'
        if np.any(difference):changed.append(index)
    assert changed==list(range(56,63))+list(range(152,159)),changed
    assert np.array_equal(cv2.imread(str(images[-1])),reference),'Loop seam is discontinuous'
    print(f'PASS: {name}; 200 frames, two brief blinks, stable crop, zero body/background changes, identical loop endpoints')
