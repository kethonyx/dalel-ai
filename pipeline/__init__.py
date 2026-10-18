"""Модуль трекинга людей и событий ухода кассира (без VLM).

ingest   — кадры ролика с временем из PTS;
tracking — детекция людей (RT-DETR) и трекинг (ByteTrack), кэш tracks.parquet;
events   — кассир, зона рабочего места, шкала занятости, события, кэш events.json.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "tracking.yaml"
CACHE_DIR = ROOT / "data" / "cache"


def load_config(path: Path | None = None) -> dict:
    return yaml.safe_load(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def video_key(video: Path) -> str:
    """Имя ролика для кэша: в именах файлов бывает кириллическая «Х», приводим к латинской."""
    return video.stem.replace("Х", "X")


def cache_dir(video: Path) -> Path:
    d = CACHE_DIR / video_key(video)
    d.mkdir(parents=True, exist_ok=True)
    return d
