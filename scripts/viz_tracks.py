"""Debug-видео трекинга: рамки с ID, зона рабочего места, полоса занятости, метки событий.

    python scripts/viz_tracks.py X-20 X-26 X-30 [--force]   # --force: пересчитать треки

Рамки: зелёная — кассир (и его продолжения после смены ID), оранжевая — другой подтверждённый
трек, серая — неподтверждённый (средний score ниже tracks.min_track_score; в занятости не участвует).
Внизу две полосы: верхняя — сырая занятость зоны, нижняя — после сглаживания; белый курсор —
текущий кадр; вертикальные метки — события (D уход, R возврат, I вторжение, E вошёл другой человек).
Результат: data/debug/<видео>_tracks.mp4. Кадры датасета: только локально, не публиковать.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import ROOT, events, ingest, load_config, tracking  # noqa: E402

BAR_H = 44
EVENT_STYLE = {"departure": ((0, 0, 255), "D"), "return": ((0, 200, 0), "R"), "intrusion": ((255, 0, 255), "I"),
               "entry": ((0, 165, 255), "E")}


def find_video(folder: Path, name: str) -> Path:
    for cand in (name, name.replace("X", "Х"), name.replace("Х", "X")):
        if (folder / f"{cand}.mov").exists():
            return folder / f"{cand}.mov"
    raise FileNotFoundError(f"Нет ролика {name}.mov в {folder}")


def draw_bar(width: int, occupancy: list, evs: list, t_now: float, t_end: float) -> np.ndarray:
    bar = np.full((BAR_H, width, 3), 30, np.uint8)
    x_of = lambda t: int(t / max(t_end, 1e-6) * (width - 1))  # noqa: E731
    for k, (t, raw, smooth) in enumerate(occupancy):
        x0 = x_of(t)
        x1 = x_of(occupancy[k + 1][0]) if k + 1 < len(occupancy) else width
        for row, val in ((0, raw), (1, smooth)):
            color = (0, 160, 0) if val else (0, 0, 140)
            cv2.rectangle(bar, (x0, 4 + row * 16), (max(x0, x1 - 1), 16 + row * 16), color, -1)
    for ev in evs:
        color, letter = EVENT_STYLE[ev["type"]]
        x = x_of(ev["t"])
        cv2.line(bar, (x, 0), (x, BAR_H - 1), color, 2)
        cv2.putText(bar, letter, (min(x + 2, width - 12), BAR_H - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
    cv2.line(bar, (x_of(t_now), 0), (x_of(t_now), BAR_H - 1), (255, 255, 255), 1)
    return bar


_detector = None


def get_tracks(video: Path, cfg: dict, force: bool):
    """Треки из кэша; детектор (≈50 с загрузки) создаётся, только если пересчёт действительно нужен."""
    global _detector
    if not force and (hit := tracking.cached_tracks(video, cfg)) is not None:
        return hit
    if _detector is None:
        d = cfg["detector"]
        _detector = tracking.PersonDetector(d["model"], d["score_threshold"], d["device"])
    return tracking.track_video(video, cfg, _detector, force=True)


def render(video: Path, out: Path, cfg: dict, force: bool) -> dict:
    df, meta = get_tracks(video, cfg, force)
    res = events.detect_events(video, cfg, (df, meta))
    confirmed = events.confirmed_tracks(df, cfg["tracks"]["min_track_score"])
    cashier = set(res["cashier_tracks"])
    by_t = {t: g for t, g in df.groupby("t")}
    t_end = meta["frame_times"][-1] if meta["frame_times"] else 1.0
    writer = None
    for t, frame in ingest.iter_frames(video, cfg["ingest"]["fps"]):
        img = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        if res["zone"]:
            z = [int(v) for v in res["zone"]]
            cv2.rectangle(img, (z[0], z[1]), (z[2], z[3]), (255, 255, 0), 1)
        g = by_t.get(t)
        for r in ([] if g is None else g.itertuples()):
            tid = int(r.track_id)
            color, thick = (((0, 220, 0), 2) if tid in cashier else ((0, 165, 255), 2) if tid in confirmed
                            else ((150, 150, 150), 1))
            cv2.rectangle(img, (int(r.x1), int(r.y1)), (int(r.x2), int(r.y2)), color, thick)
            cv2.putText(img, f"#{tid} {r.score:.2f}", (int(r.x1) + 2, int(r.y1) + 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
        recent = [e for e in res["events"] if 0 <= t - e["t"] <= 1.5]
        cv2.putText(img, f"t={t:.1f}s", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        for k, e in enumerate(recent):
            cv2.putText(img, e["type"].upper(), (6, 46 + 24 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        EVENT_STYLE[e["type"]][0], 2)
        canvas = np.vstack([img, draw_bar(img.shape[1], res["occupancy"], res["events"], t, t_end)])
        if writer is None:
            writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), cfg["ingest"]["fps"],
                                     (canvas.shape[1], canvas.shape[0]))
        writer.write(canvas)
    if writer is not None:
        writer.release()
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--videos-dir", type=Path, default=ROOT / "data" / "videos")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "debug")
    ap.add_argument("--force", action="store_true", help="пересчитать треки, даже если есть кэш")
    args = ap.parse_args()

    cfg = load_config()
    args.out.mkdir(parents=True, exist_ok=True)
    for name in args.videos:
        video = find_video(args.videos_dir, name)
        out = args.out / f"{name.replace('Х', 'X')}_tracks.mp4"
        res = render(video, out, cfg, args.force)
        evs = ", ".join(f"{e['type']}@{e['t']:.1f}" + (f"#{e['track_id']}" if e.get("track_id") is not None else "")
                        for e in res["events"]) or "-"
        print(f"{name}: кассир {res['cashier_tracks']}, зона {res['zone']}, события: {evs} -> {out}", flush=True)


if __name__ == "__main__":
    main()
