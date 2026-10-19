"""Preserve portrait detail around a generated mouth without averaging lip motion."""
import cv2
import numpy as np


def smoothstep(start, end, value):
    value = np.clip((value - start) / (end - start), 0, 1)
    return value * value * (3 - 2 * value)


class MouthCompositor:
    def __init__(self, profile):
        self.profile = profile
        self.cache = {}
        self.regions = {}
        self.reset()

    def reset(self):
        self.offset = None
        self.last_delta = None
        self.attack = 0
        self.release = 0
        self.last_bbox = None

    def masks(self, shape, bbox):
        key = (*shape[:2], *bbox)
        if key in self.cache:
            return self.cache[key]
        y1, y2, x1, x2 = bbox
        height, width = y2 - y1, x2 - x1
        center = np.array(self.profile['center']) * [shape[1], shape[0]] - [x1, y1]
        span = self.profile['width'] * shape[1]
        angle = self.profile['angle']
        yy, xx = np.mgrid[:height, :width].astype(np.float32)
        dx, dy = xx - center[0], yy - center[1]
        x = (dx * np.cos(angle) + dy * np.sin(angle)) / span
        y = (-dx * np.sin(angle) + dy * np.cos(angle)) / span

        def ellipse(rx, upper, lower, feather):
            radius = np.sqrt((x / rx) ** 2 + (y / np.where(y < 0, upper, lower)) ** 2)
            return (1 - smoothstep(feather, 1, radius)).astype(np.float32)[..., None]

        # The upper edge stops below the nostrils. The lower edge allows an open
        # mouth but preserves the original chin silhouette and neck texture.
        inner = ellipse(.70, .26, .49, .80)
        outer = ellipse(.92, .39, .77, .60)
        if 'nose_floor' in self.profile:
            top = self.profile['nose_floor'] * shape[0]
            keep_nose = smoothstep(top, top+span*.08, yy+y1)[..., None]
            inner *= keep_nose
            outer *= keep_nose
        ring = (outer[..., 0] > .08) & (inner[..., 0] < .02)
        self.cache[key] = inner, outer, ring
        return self.cache[key]

    def compose(self, frame, prediction, bbox):
        y1, y2, x1, x2 = bbox
        inner, outer, ring = self.masks(frame.shape, bbox)
        key = (*frame.shape[:2], *bbox)
        if key not in self.regions:
            ys, xs = np.nonzero(outer[..., 0] > 0)
            padding = int(np.ceil(max(1.2, (x2-x1)/100)*3))
            self.regions[key] = (max(0,int(ys.min())-padding),min(y2-y1,int(ys.max())+padding+1),
                                 max(0,int(xs.min())-padding),min(x2-x1,int(xs.max())+padding+1))
        top, bottom, left, right = self.regions[key]
        source = frame[y1+top:y1+bottom, x1+left:x1+right].astype(np.float32)
        predicted = cv2.resize(prediction.astype(np.float32), (x2-x1, y2-y1), interpolation=cv2.INTER_CUBIC)[top:bottom,left:right]
        predicted = np.clip(predicted, 0, 255)
        inner, outer, ring = inner[top:bottom,left:right], outer[top:bottom,left:right], ring[top:bottom,left:right]
        # Estimate colour only in the surrounding skin, never from lips/teeth.
        skin = ring & (source.min(axis=2) > 55) & (source.max(axis=2) < 248)
        samples = (source-predicted)[skin][::3]
        correction = np.clip(np.median(samples, axis=0), -24, 24) if len(samples) > 30 else np.zeros(3)
        self.offset = correction if self.offset is None else self.offset*.75 + correction*.25
        predicted = np.clip(predicted+self.offset, 0, 255)
        sigma = max(1.2, (x2-x1)/100)
        source_low = cv2.GaussianBlur(source, (0, 0), sigma)
        predicted_low = cv2.GaussianBlur(predicted, (0, 0), sigma)
        # Broad, low-frequency deformation blends gradually. Original fine skin
        # detail survives outside the lip core; the generated lip core is intact.
        delta = outer*(predicted_low-source_low) + inner*((predicted-predicted_low)-(source-source_low))
        self.last_delta = delta
        self.last_bbox = tuple(bbox)
        self.last_region = (y1+top,y1+bottom,x1+left,x1+right)
        self.attack = min(3, self.attack+1)
        self.release = 2
        strength = [.72, .94, 1][self.attack-1]
        output = frame.copy()
        output[y1+top:y1+bottom, x1+left:x1+right] = np.clip(source+delta*strength, 0, 255).astype(np.uint8)
        return output

    def idle(self, frame, bbox):
        if not self.release or self.last_delta is None:
            return frame
        if tuple(bbox) != self.last_bbox:
            self.reset()
            return frame
        self.release -= 1
        if not self.release:
            self.reset()
            return frame
        y1, y2, x1, x2 = self.last_region
        output = frame.copy()
        output[y1:y2, x1:x2] = np.clip(frame[y1:y2, x1:x2].astype(np.float32)+self.last_delta*.40, 0, 255).astype(np.uint8)
        return output
