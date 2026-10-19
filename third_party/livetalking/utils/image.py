
import cv2
import os
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# def read_imgs(img_list):
#     frames = []
#     logger.info('reading images...')
#     for img_path in tqdm(img_list):
#         frame = cv2.imread(img_path)
#         frames.append(frame)
#     return frames

def read_imgs(img_list):
    # Prepared facial avatars hard-link repeated neutral/blink states. Decode
    # each inode once and share immutable source arrays across their frame slots.
    keys=[]
    unique={}
    for path in img_list:
        stat=os.stat(path)
        key=(stat.st_dev,stat.st_ino)
        keys.append(key)
        unique.setdefault(key,path)
    decoded={}
    def load_image(key,path):
        image=cv2.imread(path)
        if image is None:
            raise ValueError(f"Cannot decode avatar frame: {path}")
        return key,image
    with ThreadPoolExecutor() as executor:
        futures=[executor.submit(load_image,key,path) for key,path in unique.items()]
        for future in tqdm(as_completed(futures),total=len(futures)):
            key,image=future.result()
            decoded[key]=image
    return [decoded[key] for key in keys]

def mirror_index(size, index):
    turn = index // size
    res = index % size
    if turn % 2 == 0:
        return res
    else:
        return size - res - 1 