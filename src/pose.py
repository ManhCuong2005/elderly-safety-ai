import math
import threading
from dataclasses import dataclass

import av
import numpy as np
from ai_edge_litert.interpreter import Interpreter
from PIL import Image

from .storage import read_json, safe, sha

MODEL = read_json(safe("models/movenet.json"))
CONFIG = read_json(safe("models/config.json"))
CACHE_SCHEMA = 1
TORSO = [5, 6, 11, 12]


@dataclass
class Observation:
    t: float
    width: int
    height: int
    points: np.ndarray

    def state(self, confidence):
        good = self.points[:, 2] >= confidence
        if good[TORSO].all():
            return "visible"
        return "partial" if good.sum() >= 3 else "absent"


class Pose:
    def __init__(self, prefer_yolo=True):
        self.lock = threading.Lock()
        self.backend = "movenet"
        self.yolo = None
        self.prev_center = None
        self.last_people_count = 0
        yolo_path = safe("models/yolov8n-pose.pt")
        if prefer_yolo and yolo_path.is_file():
            try:
                from ultralytics import YOLO
                self.yolo = YOLO(str(yolo_path))
                self.backend = "yolov8n-pose"
                self.size = 512
                return
            except Exception:
                self.yolo = None
        path = safe("models/" + MODEL["file"])
        if not path.is_file() or sha(path) != MODEL["sha256"]:
            raise ValueError("Thiếu MoveNet hoặc checksum trọng số sai. Chạy bước Model.")
        self.model = Interpreter(model_path=str(path), num_threads=2)
        self.model.allocate_tensors()
        self.input = self.model.get_input_details()[0]
        self.output = self.model.get_output_details()[0]["index"]
        shape = list(self.input["shape"])
        if self.input["dtype"] != np.uint8 or shape not in ([1, 192, 192, 3], [1, 256, 256, 3]):
            raise ValueError("Đầu vào MoveNet không khớp model v4 (Lightning 192 hoặc Thunder 256)")
        self.size = int(shape[1])

    def reset_tracking(self):
        with self.lock:
            self.prev_center = None
            self.last_people_count = 0

    def observe(self, t, image):
        if self.yolo is not None:
            return self._observe_yolo(t, image)
        width, height = image.size
        size = self.size
        scale = size / max(width, height)
        w, h = max(1, round(width * scale)), max(1, round(height * scale))
        left, top = (size - w) // 2, (size - h) // 2
        input_image = Image.new("RGB", (size, size))
        input_image.paste(image.convert("RGB").resize((w, h), Image.Resampling.BILINEAR), (left, top))
        tensor = np.asarray(input_image)[None]
        with self.lock:
            self.model.set_tensor(self.input["index"], tensor)
            self.model.invoke()
            y, x, confidence = self.model.get_tensor(self.output).reshape(17, 3).T
        px, py = (x * size - left) * width / w, (y * size - top) * height / h
        inside = (px >= 0) & (px < width) & (py >= 0) & (py < height)
        self.last_people_count = 1 if (confidence * inside >= 0.3).sum() >= 3 else 0
        return Observation(t, width, height, np.column_stack((px, py, confidence * inside)))

    def _observe_yolo(self, t, image):
        width, height = image.size
        with self.lock:
            res = self.yolo.predict(image, imgsz=self.size, conf=0.25, verbose=False)[0]
            kps = res.keypoints
            if kps is None or kps.xy is None or len(kps.xy) == 0:
                self.last_people_count = 0
                return Observation(t, width, height, np.zeros((17, 3), dtype=float))
            xy_all = kps.xy.cpu().numpy()
            cf_all = kps.conf.cpu().numpy()
            boxes = res.boxes.xyxy.cpu().numpy() if res.boxes is not None else None
            n = len(xy_all)
            self.last_people_count = n
            best_i = 0
            if n > 1:
                if self.prev_center is not None:
                    scored = []
                    for i in range(n):
                        c = xy_all[i, TORSO].mean(axis=0) / max(width, height)
                        area = (((boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])) / max(width * height, 1)
                                if boxes is not None else 0.1)
                        scored.append((float(np.linalg.norm(c - self.prev_center)) - 0.15 * area, i))
                    best_i = min(scored)[1]
                elif boxes is not None:
                    areas = [(boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1]) for i in range(n)]
                    best_i = int(np.argmax(areas))
            pts = np.column_stack((xy_all[best_i, :, 0], xy_all[best_i, :, 1], cf_all[best_i]))
            inside = (pts[:, 0] >= 0) & (pts[:, 0] < width) & (pts[:, 1] >= 0) & (pts[:, 1] < height)
            pts[:, 2] *= inside
            if (pts[TORSO, 2] >= 0.25).all():
                self.prev_center = pts[TORSO, :2].mean(axis=0) / max(width, height)
            return Observation(t, width, height, pts)


class Cadence:
    def __init__(self, period):
        self.period = period
        self.next = None

    def due(self, t):
        if self.next is None:
            self.next = t
        if t + 1e-8 < self.next:
            return False
        self.next += self.period * (1 + max(0, math.floor((t + 1e-8 - self.next) / self.period)))
        return True


def video_frames(path, hz, rotation_override=None):
    with av.open(str(path)) as container:
        yield from sample_frames(container, hz, rotation_override)


def sample_frames(container, hz, rotation_override=None, limit_s=None):
    clock = Cadence(1 / hz)
    stream = container.streams.video[0]
    origin = float(stream.start_time * stream.time_base) if stream.start_time is not None else None
    previous = -1.0
    for index, frame in enumerate(container.decode(stream)):
        if frame.time is None:
            raise ValueError("Frame thiếu PTS")
        if origin is None:
            origin = frame.time
        t = frame.time - origin
        if limit_s is not None and (index >= 61 * limit_s or t > limit_s
                                    or frame.width * frame.height > 3840 * 2160):
            raise ValueError("Video vượt giới hạn thời lượng, số khung hình hoặc độ phân giải.")
        if t < -1e-8 or t <= previous:
            continue
        previous = t
        if not clock.due(t):
            continue
        image = frame.to_image()
        rotation = frame.rotation % 360 if rotation_override is None else rotation_override
        if rotation:
            image = image.rotate(rotation, expand=True)
        yield t, image


def video_info(path):
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        first = next(container.decode(stream))
        duration = stream.duration * stream.time_base if stream.duration else None
        if duration is None and container.duration is not None:
            duration = container.duration / av.time_base
        rotation = first.rotation % 360
        width, height = (first.height, first.width) if rotation in {90, 270} else (first.width, first.height)
        return {"duration_s": round(float(duration), 6) if duration is not None else None,
                "fps": float(stream.average_rate) if stream.average_rate else None,
                "width": width, "height": height, "rotation_ccw": rotation,
                "codec": stream.codec_context.name}
