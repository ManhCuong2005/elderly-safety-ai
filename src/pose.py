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
    def __init__(self):
        path = safe("models/" + MODEL["file"])
        if not path.is_file() or sha(path) != MODEL["sha256"]:
            raise ValueError("Thiếu MoveNet hoặc checksum trọng số sai. Chạy bước Model.")
        self.lock = threading.Lock()
        self.model = Interpreter(model_path=str(path), num_threads=2)
        self.model.allocate_tensors()
        self.input = self.model.get_input_details()[0]
        self.output = self.model.get_output_details()[0]["index"]
        if self.input["dtype"] != np.uint8 or list(self.input["shape"]) != [1, 192, 192, 3]:
            raise ValueError("Đầu vào MoveNet không khớp model v4")

    def observe(self, t, image):
        width, height = image.size
        scale = 192 / max(width, height)
        w, h = max(1, round(width * scale)), max(1, round(height * scale))
        left, top = (192 - w) // 2, (192 - h) // 2
        input_image = Image.new("RGB", (192, 192))
        input_image.paste(image.convert("RGB").resize((w, h), Image.Resampling.BILINEAR), (left, top))
        tensor = np.asarray(input_image)[None]
        with self.lock:
            self.model.set_tensor(self.input["index"], tensor)
            self.model.invoke()
            y, x, confidence = self.model.get_tensor(self.output).reshape(17, 3).T
        px, py = (x * 192 - left) * width / w, (y * 192 - top) * height / h
        inside = (px >= 0) & (px < width) & (py >= 0) & (py < height)
        return Observation(t, width, height, np.column_stack((px, py, confidence * inside)))


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
