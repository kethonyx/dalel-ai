"""Детекция людей (RT-DETR, HF transformers) и трекинг (ByteTrack из supervision).

Только bbox класса person: лица не распознаются и не анализируются.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd

from . import cache_dir, ingest, load_config

TRACK_COLUMNS = ["t", "track_id", "x1", "y1", "x2", "y2", "score"]


def pick_device(name: str = "auto") -> str:
    import torch

    if name != "auto":
        return name
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class PersonDetector:
    """RT-DETR, батчевый инференс; на выходе по каждому кадру массив (N, 5): x1, y1, x2, y2, score."""

    def __init__(self, model_id: str, score_threshold: float, device: str = "auto"):
        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection

        self.torch = torch
        self.device = pick_device(device)
        self.threshold = score_threshold
        self.processor = AutoImageProcessor.from_pretrained(model_id)
        self.model = AutoModelForObjectDetection.from_pretrained(model_id).to(self.device).eval()
        self.person_ids = {i for i, name in self.model.config.id2label.items() if name == "person"}
        if not self.person_ids:
            raise ValueError(f"В модели {model_id} нет класса person")

    def __call__(self, frames: list[np.ndarray]) -> list[np.ndarray]:
        inputs = self.processor(images=frames, return_tensors="pt").to(self.device)
        with self.torch.no_grad():
            outputs = self.model(**inputs)
        sizes = [(f.shape[0], f.shape[1]) for f in frames]
        results = self.processor.post_process_object_detection(outputs, target_sizes=sizes, threshold=self.threshold)
        out = []
        for res in results:
            keep = [i for i, label in enumerate(res["labels"].tolist()) if label in self.person_ids]
            boxes = res["boxes"][keep].float().cpu().numpy().reshape(-1, 4)
            scores = res["scores"][keep].float().cpu().numpy().reshape(-1, 1)
            out.append(np.hstack([boxes, scores]).astype(np.float32))
        return out


def detect_video(video: Path, cfg: dict | None = None, detector: PersonDetector | None = None,
                 keep_frames: bool = False) -> Iterator[tuple[float, np.ndarray, np.ndarray | None]]:
    """(t, детекции (N, 5), кадр или None) по кадрам ролика с частотой ingest.fps."""
    cfg = cfg or load_config()
    det_cfg = cfg["detector"]
    detector = detector or PersonDetector(det_cfg["model"], det_cfg["score_threshold"], det_cfg["device"])
    frames = ingest.iter_frames(video, cfg["ingest"]["fps"])
    for batch in ingest.batched(frames, det_cfg["batch_size"]):
        dets = detector([f for _, f in batch])
        for (t, frame), d in zip(batch, dets):
            yield t, d, frame if keep_frames else None


def _settings_hash(cfg: dict) -> str:
    """Кэш треков зависит только от ingest, detector и tracker: смена порогов событий его не сбрасывает."""
    part = {k: cfg[k] for k in ("ingest", "detector", "tracker")}
    return hashlib.sha1(json.dumps(part, sort_keys=True).encode()).hexdigest()[:12]


def load_tracks(path: Path) -> tuple[pd.DataFrame, dict]:
    import pyarrow.parquet as pq

    table = pq.read_table(path)
    meta = json.loads((table.schema.metadata or {}).get(b"dalel", b"{}"))
    return table.to_pandas(), meta


def cached_tracks(video: Path, cfg: dict) -> tuple[pd.DataFrame, dict] | None:
    """Треки из кэша, если он есть и посчитан с теми же настройками ingest/detector/tracker."""
    path = cache_dir(video) / "tracks.parquet"
    if not path.exists():
        return None
    df, meta = load_tracks(path)
    return (df, meta) if meta.get("settings") == _settings_hash(cfg) else None


def track_video(video: Path, cfg: dict | None = None, detector: PersonDetector | None = None,
                force: bool = False) -> tuple[pd.DataFrame, dict]:
    """Треки ролика: DataFrame (t, track_id, x1, y1, x2, y2, score) и meta (время всех кадров, размер).

    Кэш: data/cache/{video}/tracks.parquet. Время кадров хранится в метаданных parquet, потому что
    кадры без людей нужны шкале занятости, а строк в таблице для них нет.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    import supervision as sv

    cfg = cfg or load_config()
    path = cache_dir(video) / "tracks.parquet"
    if not force and (hit := cached_tracks(video, cfg)) is not None:
        return hit
    tc = cfg["tracker"]
    tracker = sv.ByteTrack(
        track_activation_threshold=tc["track_activation_threshold"], lost_track_buffer=tc["lost_track_buffer"],
        minimum_matching_threshold=tc["minimum_matching_threshold"], frame_rate=tc["frame_rate"],
        minimum_consecutive_frames=tc["minimum_consecutive_frames"])
    rows, times, size = [], [], None
    for t, dets, frame in detect_video(video, cfg, detector, keep_frames=True):
        size = size or (int(frame.shape[1]), int(frame.shape[0]))
        times.append(t)
        found = sv.Detections(xyxy=dets[:, :4].astype(np.float64), confidence=dets[:, 4],
                              class_id=np.zeros(len(dets), dtype=int))
        tracked = tracker.update_with_detections(found)
        for box, score, tid in zip(tracked.xyxy, tracked.confidence, tracked.tracker_id):
            rows.append((t, int(tid), *(float(v) for v in box), float(score)))
    df = pd.DataFrame(rows, columns=TRACK_COLUMNS)
    meta = {"frame_times": times, "width": size[0] if size else 0, "height": size[1] if size else 0,
            "fps": cfg["ingest"]["fps"], "settings": _settings_hash(cfg)}
    table = pa.Table.from_pandas(df, preserve_index=False)
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), b"dalel": json.dumps(meta).encode()})
    pq.write_table(table, path)
    return df, meta
