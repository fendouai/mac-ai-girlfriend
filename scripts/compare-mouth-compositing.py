"""Compare identical real Wav2Lip predictions through old/new compositors."""
from pathlib import Path
import json
import pickle
import subprocess
import sys
import time

import av
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'third_party/livetalking'))
from avatars.wav2lip import audio
from utils.mouth_compositor import MouthCompositor

LOGS = ROOT / 'logs'
LOGS.mkdir(exist_ok=True)
profiles = json.loads((ROOT / 'data/avatars/mouth-profiles.json').read_text())['avatars']
wave = audio.load_wav(str(ROOT / 'data/prompt1.mp3'), 16000)[:16000*4]
audio.save_wav(wave.copy(), str(LOGS / 'mouth-test-speech.wav'), 16000)
mel = audio.melspectrogram(wave)
frames = 80
model = None
results = []
for name, profile in profiles.items():
    folder = ROOT / 'third_party/livetalking/data/avatars' / name
    bbox = pickle.loads((folder / 'coords.pkl').read_bytes())[0]
    y1, y2, x1, x2 = bbox
    prediction_file = LOGS / f'{name}-mouth-predictions.npy'
    if not prediction_file.exists():
        if model is None:
            import coremltools as ct
            model = ct.models.MLModel(str(ROOT / 'models/wav2lip256-b4.mlpackage'), compute_units=ct.ComputeUnit.ALL)
        predictions = []
        for start in range(0, frames, 4):
            faces = np.array([cv2.imread(str(folder / 'face_imgs' / f'{i:08d}.png')) for i in range(start,start+4)])
            masked = faces.copy();masked[:,128:] = 0
            network_faces = np.concatenate([masked, faces], axis=3).astype(np.float32)/255
            chunks = np.array([mel[:,int(i*80/25):int(i*80/25)+16] for i in range(start,start+4)],dtype=np.float32)[:,None]
            output = model.predict({'mel':chunks,'face':network_faces.transpose(0,3,1,2)})['prediction']
            predictions.extend(np.clip(output.transpose(0,2,3,1)*255,0,255).astype(np.uint8))
        np.save(prediction_file,np.array(predictions))
    predictions = np.load(prediction_file)
    compositor = MouthCompositor(profile)
    reference = cv2.imread(str(folder / 'full_imgs/00000000.png'))
    inner, outer, _ = compositor.masks(reference.shape,bbox)
    yy,xx = np.mgrid[0:y2-y1,0:x2-x1].astype(np.float32)
    legacy = np.clip((1-((xx/(x2-x1)-.5)/.45)**2-((yy/(y2-y1)-.80)/.24)**2)/.30,0,1)[...,None]
    boundary = (outer[...,0]>.01)&(outer[...,0]<.20)
    core = inner[...,0]>.99
    times=[];old_errors=[];new_errors=[];motion=[]
    video_path = LOGS / f'{name}-mouth-comparison-silent.mp4'
    video = av.open(str(video_path),mode='w')
    stream = video.add_stream('h264_videotoolbox',rate=25)
    stream.width=768;stream.height=512;stream.pix_fmt='yuv420p';stream.bit_rate=3000000
    snapshots=[]
    for index,prediction in enumerate(predictions):
        source = cv2.imread(str(folder / 'full_imgs' / f'{index:08d}.png'))
        previous=source.copy();roi=source[y1:y2,x1:x2]
        predicted=cv2.resize(prediction,(x2-x1,y2-y1))
        previous[y1:y2,x1:x2]=(predicted*legacy+roi*(1-legacy)).astype(np.uint8)
        started=time.perf_counter();improved=compositor.compose(source,prediction,bbox)
        times.append((time.perf_counter()-started)*1000)
        outside=np.ones(source.shape[:2],bool);outside[y1:y2,x1:x2]=outer[...,0]==0
        assert np.array_equal(improved[outside],source[outside]), 'Blink/identity changed outside the mouth'
        old_errors.append(float(np.abs(previous[y1:y2,x1:x2].astype(float)-roi)[boundary].mean()))
        new_errors.append(float(np.abs(improved[y1:y2,x1:x2].astype(float)-roi)[boundary].mean()))
        motion.append(improved[y1:y2,x1:x2][core].astype(float))
        panels=[]
        for image,label in [(previous,'Before'),(improved,'After')]:
            crop=image[max(0,y1-25):min(1024,y2+35),max(0,x1-35):min(768,x2+35)]
            panel=np.zeros((512,384,3),np.uint8);panel[32:]=cv2.resize(crop,(384,480))
            cv2.putText(panel,label,(12,23),cv2.FONT_HERSHEY_SIMPLEX,.6,(240,240,240),1,cv2.LINE_AA)
            panels.append(panel)
        side_by_side=np.concatenate(panels,axis=1)
        if index in [20,40,60]:snapshots.append(side_by_side)
        for packet in stream.encode(av.VideoFrame.from_ndarray(side_by_side,format='bgr24')):video.mux(packet)
    for packet in stream.encode():video.mux(packet)
    video.close()
    cv2.imwrite(str(LOGS / f'{name}-mouth-contact.png'),np.concatenate(snapshots,axis=0))
    final_path=LOGS / f'{name}-mouth-comparison.mp4'
    subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(video_path),'-i',str(LOGS/'mouth-test-speech.wav'),
                    '-c:v','copy','-c:a','aac','-shortest',str(final_path)],check=True)
    record=dict(avatar=name,frames=frames,mean_composite_ms=float(np.mean(times[3:])),
                p95_ms=float(np.percentile(times[3:],95)),
                former_boundary_pixel_change=float(np.mean(old_errors)),
                new_boundary_pixel_change=float(np.mean(new_errors)),
                lip_frame_difference=float(np.abs(np.diff(np.array(motion),axis=0)).mean()),
                unchanged_outside_mouth=True,video=str(final_path.relative_to(ROOT)))
    assert record['new_boundary_pixel_change']<record['former_boundary_pixel_change']*.35,record
    assert record['lip_frame_difference']>1,'Speech mouth was frozen'
    results.append(record);print(json.dumps(record),flush=True)
(LOGS/'mouth-comparison-results.json').write_text(json.dumps(results,indent=2)+'\n')
