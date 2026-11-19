import csv
import math
import json
from pathlib import Path
import re
import time
import cv2

DATASET=Path(__file__).resolve().parents[2]/'datasets'


def input_layout(source,requested='auto'):
    if requested!='auto':return requested
    if isinstance(source,int):return 'rgb'
    path=Path(source).resolve()
    metadata=DATASET/'metadata/input_layouts.json'
    if path.parent==(DATASET/'raw').resolve() and metadata.is_file():
        rows=json.loads(metadata.read_text(encoding='utf-8'))
        for row in rows:
            if row['file_name']==path.name and row.get('verified'):
                return row['input_layout']
    return 'rgb'


def crop_rgbd(frame):
    h,w=frame.shape[:2]
    if w%2 or not 2<=w/h<=3:
        raise ValueError('UR RGB/depth composite must contain equal left and right panels')
    return frame[:,w//2:].copy()


def number(path):
    return int(re.findall(r"\d+", path.stem)[-1])


class Source:
    def __init__(self, source, sync_path=None, fps=15, width=640, height=480, layout='auto'):
        self.cap, self.files = None, None
        self.live = isinstance(source, int)
        self.layout=input_layout(source,layout)
        if self.layout not in ('rgb','ur-rgbd'):raise ValueError('Unknown input layout')
        if self.live and self.layout!='rgb':raise ValueError('Composite mode is for dataset video only')
        self.start = time.monotonic()
        self.index, self.last_t = 0, -1.0
        if not self.live and Path(source).is_dir():
            self.files = sorted(Path(source).rglob("*.png"), key=number)
            if not self.files or not sync_path:
                raise ValueError("Sequences require PNG frames and synchronization CSV")
            with open(sync_path, newline="") as f:
                self.timestamps = {int(row[0]): float(row[1])/1000 for row in csv.reader(f) if row}
        else:
            self.cap = cv2.VideoCapture(source)
            if not self.cap.isOpened():
                self.cap.release()
                raise RuntimeError(f"Cannot open camera/video: {source}")
            if self.live:
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                self.cap.set(cv2.CAP_PROP_FPS, fps)
            self.fps = self.cap.get(cv2.CAP_PROP_FPS)
            count=self.cap.get(cv2.CAP_PROP_FRAME_COUNT)
            self.expected_frames=int(count) if math.isfinite(count) and count>0 else None
            if not self.live and (not math.isfinite(self.fps) or self.fps <= 0):
                self.close()
                raise ValueError("Video has invalid FPS")

    def __iter__(self):
        return self

    def __next__(self):
        if self.files is not None:
            if self.index >= len(self.files):
                raise StopIteration
            path = self.files[self.index]
            t = self.timestamps[number(path)]
            frame = cv2.imread(str(path))
            if frame is None:
                raise RuntimeError(f"Unreadable image: {path}")
        else:
            ok, frame = self.cap.read()
            if not ok:
                if self.live:
                    raise RuntimeError("Camera disconnected or read failed")
                if self.expected_frames and self.index<self.expected_frames-1:
                    raise RuntimeError('Video decode ended before the advertised frame count')
                raise StopIteration
            t = time.monotonic()-self.start if self.live else self.cap.get(cv2.CAP_PROP_POS_MSEC)/1000
            if not self.live and t <= self.last_t:
                t = self.index/self.fps  # constant-rate fallback
        if self.layout=='ur-rgbd':frame=crop_rgbd(frame)
        if t <= self.last_t:
            raise ValueError("Non-monotonic source timestamp")
        self.last_t = t
        self.index += 1
        return t, frame

    def close(self):
        if self.cap:
            self.cap.release()
