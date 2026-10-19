###############################################################################
#  Copyright (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking
#  email: lipku@foxmail.com
# 
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#  
#       http://www.apache.org/licenses/LICENSE-2.0
# 
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################
#
#  Wav2Lip 数字人 — 迁移自 lipreal.py + lipasr.py
#

import math
import torch
import numpy as np

import os
import sys
import time
import cv2
import glob
import pickle
import json
from pathlib import Path

import queue
from queue import Queue
from threading import Thread, Event
import torch.multiprocessing as mp

from avatars.audio_features.mel import MelASR
import asyncio
from av import AudioFrame, VideoFrame
from avatars.wav2lip.models import Wav2Lip
from avatars.base_avatar import BaseAvatar

from tqdm import tqdm
from utils.logger import logger
from utils.image import read_imgs, mirror_index
from utils.device import initialize_device
from utils.mouth_compositor import MouthCompositor
from registry import register

device = initialize_device()
logger.info('Using {} for inference.'.format(device))

def _load(checkpoint_path):
    # Load on CPU first, then move to CUDA/MPS; only model tensors are needed.
    return torch.load(checkpoint_path, map_location="cpu", weights_only=True)

class CoreMLWav2Lip:
    def __init__(self, path):
        import coremltools as ct
        self.network = ct.models.MLModel(path, compute_units=ct.ComputeUnit.ALL)

    def predict(self, mel, face):
        return self.network.predict({"mel": mel.astype(np.float32),
                                     "face": face.astype(np.float32)})["prediction"]


def load_model(path):
    coreml_path = os.path.abspath("../../models/wav2lip256-b4.mlpackage")
    if sys.platform == "darwin" and os.environ.get("HEX_AVATAR_BACKEND", "auto") in ("auto", "coreml") and os.path.isdir(coreml_path):
        logger.info("Using Core ML (Apple CPU/GPU/Neural Engine) for original Wav2Lip256")
        return CoreMLWav2Lip(coreml_path)
    model = Wav2Lip()
    logger.info("Load checkpoint from: {}".format(path))
    checkpoint = _load(path)
    s = checkpoint["state_dict"]
    new_s = {}
    for k, v in s.items():
        new_s[k.replace('module.', '')] = v
    model.load_state_dict(new_s)

    return model.to(device).eval()

def load_avatar(avatar_id):
    avatar_path = f"./data/avatars/{avatar_id}"
    full_imgs_path = f"{avatar_path}/full_imgs" 
    face_imgs_path = f"{avatar_path}/face_imgs" 
    coords_path = f"{avatar_path}/coords.pkl"
    
    with open(coords_path, 'rb') as f:
        coord_list_cycle = pickle.load(f)
    frame_list_cycle = None
    input_img_list = glob.glob(os.path.join(full_imgs_path, '*.[jpJP][pnPN]*[gG]'))
    input_img_list = sorted(input_img_list, key=lambda x: int(os.path.splitext(os.path.basename(x))[0]))
    frame_list_cycle = read_imgs(input_img_list)
    input_face_list = glob.glob(os.path.join(face_imgs_path, '*.[jpJP][pnPN]*[gG]'))
    input_face_list = sorted(input_face_list, key=lambda x: int(os.path.splitext(os.path.basename(x))[0]))
    face_list_cycle = read_imgs(input_face_list)

    # 生成中断/源视频不可读 → 只剩 coords.pkl、没有帧图。直接开跑会让推理线程
    # mirror_index(0, index) 除零崩溃，画面和声音一起消失（都走同一路 WebRTC）。
    # 这里提前拦下并给出可读原因，让 offer 被明确拒绝而不是带病建会话。
    if not frame_list_cycle or not face_list_cycle:
        raise ValueError(
            f"形象 {avatar_id} 数据不完整: full_imgs={len(frame_list_cycle)} 张, "
            f"face_imgs={len(face_list_cycle)} 张。请重新生成（确认源视频可读）或换用其他形象。"
        )

    return frame_list_cycle,face_list_cycle,coord_list_cycle

@torch.no_grad()
def warm_up(batch_size,model,modelres):
    # 预热函数
    logger.info('warmup model...')
    if isinstance(model, CoreMLWav2Lip):
        model.predict(np.zeros((batch_size, 1, 80, 16), np.float32),
                      np.zeros((batch_size, 6, modelres, modelres), np.float32))
        return
    img_batch = torch.ones(batch_size, 6, modelres, modelres, device=device, dtype=next(model.parameters()).dtype)
    mel_batch = torch.ones(batch_size, 1, 80, 16, device=device, dtype=next(model.parameters()).dtype)
    model(mel_batch, img_batch)

@register("avatar", "wav2lip")
class LipReal(BaseAvatar):
    @torch.no_grad()
    def __init__(self, opt, model, avatar):
        super().__init__(opt)

        #self.fps = opt.fps # 20 ms per frame
        
        # self.batch_size = opt.batch_size
        # self.idx = 0
        # self.res_frame_queue = Queue(self.batch_size*2)
        self.model = model

        self.frame_list_cycle,self.face_list_cycle,self.coord_list_cycle = avatar
        profiles_path = Path(__file__).resolve().parents[3]/'data/avatars/mouth-profiles.json'
        profiles = json.loads(profiles_path.read_text()) if profiles_path.exists() else {}
        profile = profiles.get('avatars', {}).get(opt.avatar_id)
        source_path = Path('data/avatars')/opt.avatar_id/'source.json'
        if profile and source_path.exists():
            reference_hash = json.loads(source_path.read_text()).get('reference_sha256')
            if reference_hash and reference_hash != profile.get('reference_sha256'):
                logger.warning('Mouth profile does not match this portrait; using legacy compositing')
                profile = None
        self.mouth_compositor = MouthCompositor(profile) if profile else None
        self._mouth_epoch = self.audio_epoch
        if self.mouth_compositor:
            logger.info('Using landmark-aligned multiband mouth compositing for %s', opt.avatar_id)
        self.asr = MelASR(opt,self)
        self.asr.warm_up()
    
    def inference_batch(self, index, audiofeat_batch):
        # 这里的 index 是针对当前 avatar 的索引
        # 返回一个 batch 的推理结果，batch 大小由 self.batch_size 决定
        length = len(self.face_list_cycle)
        img_batch = []
        for i in range(self.batch_size):
            idx = mirror_index(length, index + i)
            face = self.face_list_cycle[idx]
            img_batch.append(face)
        img_batch, audiofeat_batch = np.asarray(img_batch), np.asarray(audiofeat_batch)

        img_masked = img_batch.copy()
        img_masked[:, face.shape[0]//2:] = 0

        img_batch = np.concatenate((img_masked, img_batch), axis=3) / 255.
        audiofeat_batch = np.reshape(audiofeat_batch, [len(audiofeat_batch), audiofeat_batch.shape[1], audiofeat_batch.shape[2], 1])
        
        if isinstance(self.model, CoreMLWav2Lip):
            pred = self.model.predict(np.transpose(audiofeat_batch, (0, 3, 1, 2)),
                                      np.transpose(img_batch, (0, 3, 1, 2)))
            return pred.transpose(0, 2, 3, 1) * 255.

        img_batch = torch.from_numpy(np.transpose(img_batch, (0, 3, 1, 2))).to(device=device, dtype=next(self.model.parameters()).dtype)
        audiofeat_batch = torch.from_numpy(np.transpose(audiofeat_batch, (0, 3, 1, 2))).to(device=device, dtype=next(self.model.parameters()).dtype)

        with torch.no_grad():
            pred = self.model(audiofeat_batch, img_batch)
        pred = pred.float().cpu().numpy().transpose(0, 2, 3, 1) * 255.
        return pred

    def paste_back_frame(self,pred_frame,idx:int):
        bbox = self.coord_list_cycle[idx]
        self._sync_mouth_epoch()
        if self.mouth_compositor:
            return self.mouth_compositor.compose(self.frame_list_cycle[idx], pred_frame, bbox)
        combine_frame = self.frame_list_cycle[idx].copy()
        y1, y2, x1, x2 = bbox
        res_frame = cv2.resize(pred_frame.astype(np.uint8),(x2-x1,y2-y1))
        # Preserve source eyes/hair and full-resolution identity details. The
        # Wav2Lip output is only 256px; paste its mouth/jaw through a soft mask.
        key = (y2-y1, x2-x1)
        if not hasattr(self, '_blend_masks'):
            self._blend_masks = {}
        if key not in self._blend_masks:
            yy, xx = np.mgrid[0:key[0], 0:key[1]].astype(np.float32)
            radius = ((xx/key[1] - 0.5)/0.45)**2 + ((yy/key[0] - 0.80)/0.24)**2
            self._blend_masks[key] = np.clip((1-radius)/0.30, 0, 1)[..., None]
        alpha = self._blend_masks[key]
        source = combine_frame[y1:y2, x1:x2]
        combine_frame[y1:y2, x1:x2] = (res_frame*alpha + source*(1-alpha)).astype(np.uint8)
        return combine_frame

    def _sync_mouth_epoch(self):
        if self._mouth_epoch != self.audio_epoch:
            if self.mouth_compositor:self.mouth_compositor.reset()
            self._mouth_epoch = self.audio_epoch

    def postprocess_idle_frame(self, frame, idx):
        self._sync_mouth_epoch()
        if self.mouth_compositor:
            return self.mouth_compositor.idle(frame, self.coord_list_cycle[idx])
        return frame

