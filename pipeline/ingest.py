"""Чтение ролика и сэмплинг кадров.

Время кадра берётся из PTS контейнера (CAP_PROP_POS_MSEC в FFmpeg-бэкенде OpenCV), а не
из индекса и fps: в роликах датасета бывают выпавшие кадры (шаг 66,7 мс вместо 33,3 мс),
и время по индексу к концу ролика расходится с реальным.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np


class IngestError(RuntimeError):
    pass


def iter_frames(video: Path, fps: float = 5.0) -> Iterator[tuple[float, np.ndarray]]:
    """Кадры RGB с шагом ~1/fps по времени PTS: (t_sec, кадр H×W×3 uint8).

    Берётся первый кадр, чьё время не раньше очередной отметки сетки 0, 1/fps, 2/fps, ...;
    остальные кадры только grab() (без декодирования в изображение).
    """
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise IngestError(f"Не удалось открыть видео {video}")
    step, next_t = 1.0 / fps, 0.0
    try:
        while cap.grab():
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if t + 1e-6 < next_t:
                continue
            ok, frame = cap.retrieve()
            if not ok:
                break
            yield round(t, 3), cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            while next_t <= t + 1e-6:  # после пропуска кадров сетка догоняет текущее время
                next_t += step
    finally:
        cap.release()


def batched(frames: Iterator[tuple[float, np.ndarray]], size: int) -> Iterator[list[tuple[float, np.ndarray]]]:
    batch: list[tuple[float, np.ndarray]] = []
    for item in frames:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
