"""Дверь кассы по разнице пикселей, без вопросов к модели на каждом кадре.

Вопрос «дверь открыта?» модель путает (тесный кроп: в Х-31 дверь закрыта, ответы «да» на 3 из 5
кадров). А открытая дверь хорошо видна как изменение картинки в рамке двери, которое держится
секундами: проём на месте полотна. Человек, прошедший мимо, даёт всплеск на 2–4 с.

  1. модель один раз находит дверь на первом кадре (grounding);
  2. ffmpeg 2 кадра/с, кадр выравнивается по первому (ECC: камера на штативе чуть дрожит);
  3. люди вырезаются из сравнения (детектор RT-DETR, Apache-2.0), яркость в рамке нормируется;
  4. доля изменившихся пикселей в рамке -> ряд signal["rows"], правило kind="signal" в rules.py.

Опорный кадр — первый: если дверь открыта с самого начала, изменения не будет (ограничение).
Нет torch/transformers/opencv -> сигнала нет, правило двери молча не срабатывает.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from . import vlm

FPS = 2
SIDE = 640
DOOR_LABELS = ["glass door of the room", "door"]
DIFF_LEVEL = 30  # порог разницы нормированной яркости пикселя
DETECTOR = "PekingU/rtdetr_v2_r18vd"

_det = None


def _detector():
    global _det
    if _det is None:
        import torch
        from transformers import AutoImageProcessor, RTDetrV2ForObjectDetection

        dev = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
        model = RTDetrV2ForObjectDetection.from_pretrained(DETECTOR).to(dev).eval()
        person = [k for k, v in model.config.id2label.items() if v == "person"][0]
        _det = (AutoImageProcessor.from_pretrained(DETECTOR), model, dev, person)
    return _det


def _people(img: Image.Image) -> list[list[float]]:
    import torch

    proc, model, dev, person = _detector()
    with torch.no_grad():
        out = model(**proc(images=img, return_tensors="pt").to(dev))
    r = proc.post_process_object_detection(out, threshold=0.5, target_sizes=[img.size[::-1]])[0]
    return [b for b, lab in zip(r["boxes"].tolist(), r["labels"].tolist()) if lab == person]


def find_door(first_frame: Path) -> tuple | None:
    from .pipeline import to_jpeg

    img = Image.open(first_frame).convert("RGB")
    for label in DOOR_LABELS:
        found = vlm.ground(to_jpeg(img, SIDE), [label], img.width, img.height)
        if found:
            return found[0]["box"]
    return None


def door_signal(video: Path, box: tuple, deadline_fn=lambda: False) -> dict:
    """{"box", "rows": [{"t", "d", "light"}], "max_shift"}; d — доля изменившихся пикселей в рамке."""
    import cv2
    import numpy as np

    with tempfile.TemporaryDirectory(prefix="door_") as tmp:
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps={FPS},scale=-2:{SIDE}",
                        "-q:v", "3", str(Path(tmp) / "f_%05d.jpg")], check=True, capture_output=True)
        paths = sorted(Path(tmp).glob("f_*.jpg"))
        if not paths:
            return {"box": box, "rows": [], "max_shift": 0.0}
        first = Image.open(paths[0]).convert("RGB")
        W, H = first.size
        x1, y1, x2, y2 = int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)
        if x2 - x1 < 8 or y2 - y1 < 8:
            return {"box": box, "rows": [], "max_shift": 0.0}

        def gray(img):
            return cv2.GaussianBlur(cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY), (5, 5), 0)

        def small(a):
            return cv2.resize(a, (W // 2, H // 2)).astype(np.float32)

        def norm(a):  # выключенный свет не должен выглядеть как открытая дверь
            r = a[y1:y2, x1:x2].astype(np.float32)
            return (r - r.mean()) / (r.std() + 1e-3) * 40

        g0 = gray(first)
        ref_small, ref_norm, ref_mean = small(g0), norm(g0), float(g0.mean()) + 1e-3
        rows, max_shift = [], 0.0
        for k, p in enumerate(paths):
            if deadline_fn():
                break
            img = first if k == 0 else Image.open(p).convert("RGB")
            g = gray(img)
            warp = np.eye(2, 3, dtype=np.float32)
            if k:
                try:
                    _, warp = cv2.findTransformECC(ref_small, small(g), warp, cv2.MOTION_EUCLIDEAN,
                                                   (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4), None, 1)
                    warp[:, 2] *= 2
                except cv2.error:
                    pass
                g = cv2.warpAffine(g, warp, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                   borderMode=cv2.BORDER_REPLICATE)
            max_shift = max(max_shift, float(np.hypot(*warp[:, 2])))
            mask = np.ones((H, W), bool)
            for a, b, c, d in _people(img):
                m = 0.1 * (c - a)
                mask[max(0, int(b - m)):int(d + m), max(0, int(a - m)):int(c + m)] = False
            mk = mask[y1:y2, x1:x2]
            changed = (np.abs(norm(g) - ref_norm) > DIFF_LEVEL) & mk
            rows.append({"t": round(k / FPS, 2), "d": round(float(changed.sum() / max(1, mk.sum())), 3),
                         "light": round(float(g.mean()) / ref_mean, 3)})
    return {"box": box, "rows": rows, "max_shift": round(max_shift, 1)}


def available() -> bool:
    try:
        import cv2  # noqa: F401
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except ImportError:
        return False
