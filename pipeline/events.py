"""События по трекам: кассир, зона рабочего места, шкала занятости, уход / возвращение / вторжение.

Зона строится от рамки кассира в этом ролике, а не по фиксированным координатам: финальное
видео снято под другим углом. Кассир опознаётся только по треку (bbox), без лиц.
Кэш: data/cache/{video}/events.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import cache_dir, load_config, video_key

Box = tuple[float, float, float, float]


# ---------------------------------------------------------- шкала занятости ---

def fill_gaps(values: list[bool], times: list[float], max_gap_sec: float) -> list[bool]:
    """Провалы (серии False) короче max_gap_sec между двумя True заполняются True.

    Длина провала = время от последнего True до следующего True: при 5 fps одиночный пропущенный
    кадр — это провал 0,4 с. Провалы в начале и в конце шкалы не трогаются.
    """
    out = list(values)
    last_true = None
    for i, v in enumerate(values):
        if not v:
            continue
        if last_true is not None and i - last_true > 1 and times[i] - times[last_true] <= max_gap_sec:
            for j in range(last_true + 1, i):
                out[j] = True
        last_true = i
    return out


def find_absences(values: list[bool], times: list[float], min_sec: float, min_presence_sec: float = 0.0,
                  end_min_sec: float | None = None) -> list[tuple[int, int | None]]:
    """Отсутствия: серии False не короче min_sec после того, как зона хоть раз была занята
    непрерывно не меньше min_presence_sec. Серия, идущая до конца шкалы, засчитывается уже при
    end_min_sec (по умолчанию = min_sec): ролик могут обрезать вскоре после ухода.

    Возвращает (индекс первого пустого кадра, индекс первого занятого кадра после | None, если пусто
    до конца). Длина = время возврата (или последнего кадра) минус время первого пустого кадра.
    """
    end_min_sec = min_sec if end_min_sec is None else end_min_sec
    out = []
    i, n = 0, len(values)
    settled = False
    while i < n:
        if values[i]:
            j = i
            while j < n and values[j]:
                j += 1
            settled = settled or times[j - 1] - times[i] >= min_presence_sec
            i = j
            continue
        j = i
        while j < n and not values[j]:
            j += 1
        if j < n:
            long_enough = times[j] - times[i] >= min_sec
        else:
            long_enough = times[-1] - times[i] >= end_min_sec
        if settled and long_enough:
            out.append((i, j if j < n else None))
        i = j
    return out


# ----------------------------------------------------------------- геометрия ---

def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def in_zone(box: Box, zone: Box, iou_threshold: float) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return (zone[0] <= cx <= zone[2] and zone[1] <= cy <= zone[3]) or iou(box, zone) >= iou_threshold


def expand_box(box: Box, factor: float, width: int, height: int) -> Box:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    hw, hh = (box[2] - box[0]) * factor / 2, (box[3] - box[1]) * factor / 2
    return (max(0.0, cx - hw), max(0.0, cy - hh), min(float(width), cx + hw), min(float(height), cy + hh))


def _motion(g: pd.DataFrame) -> float:
    """Медианное смещение центра рамки между соседними кадрами в долях высоты рамки."""
    if len(g) < 2:
        return 0.0
    cx, cy = (g.x1 + g.x2).to_numpy() / 2, (g.y1 + g.y2).to_numpy() / 2
    h = float(np.median((g.y2 - g.y1).to_numpy())) or 1.0
    return float(np.median(np.hypot(np.diff(cx), np.diff(cy)))) / h


# ------------------------------------------------------------ кассир и зона ---

def confirmed_tracks(df: pd.DataFrame, min_score: float) -> set[int]:
    return set(df.groupby("track_id").score.mean().loc[lambda s: s >= min_score].index.astype(int))


def pick_cashier(df: pd.DataFrame, times: list[float], confirmed: set[int], cfg: dict) -> int | None:
    """Трек, который в первые init_sec (с первого появления людей) дольше всех, увереннее и неподвижнее всех в кадре."""
    d = df[df.track_id.isin(confirmed)]
    if d.empty:
        return None
    t0 = float(d.t.min())
    win = d[d.t <= t0 + cfg["init_sec"]]
    n_frames = max(1, sum(t0 <= t <= t0 + cfg["init_sec"] for t in times))
    best, best_score = None, -1e9
    for tid, g in win.groupby("track_id"):
        # доля кадров × средний score: неподвижный слабый силуэт за стеклом не должен обыгрывать кассира
        score = len(g) / n_frames * float(g.score.mean()) - cfg["motion_penalty"] * _motion(g.sort_values("t"))
        if score > best_score:
            best, best_score = int(tid), score
    return best


def cashier_tracks(df: pd.DataFrame, first: int, cfg: dict) -> set[int]:
    """Трек кассира плюс его продолжения после обрыва (ID switch): новый трек, начавшийся вскоре
    после конца трека кассира рядом с местом обрыва, считается тем же человеком."""
    spans = {int(tid): g.sort_values("t") for tid, g in df.groupby("track_id")}
    ids, frontier = {first}, [first]
    while frontier:
        last = spans[frontier.pop()].iloc[-1]
        cx, cy, h = (last.x1 + last.x2) / 2, (last.y1 + last.y2) / 2, last.y2 - last.y1
        for tid, g in spans.items():
            if tid in ids:
                continue
            start = g.iloc[0]
            if 0 < start.t - last.t <= cfg["stitch_sec"] and \
                    np.hypot((start.x1 + start.x2) / 2 - cx, (start.y1 + start.y2) / 2 - cy) <= cfg["stitch_dist"] * h:
                ids.add(tid)
                frontier.append(tid)
    return ids


def workplace_zone(df: pd.DataFrame, cashier: set[int], width: int, height: int, cfg: dict) -> Box | None:
    """Медианная рамка кассира за самое неподвижное окно init_sec в первых search_sec, расширенная в expand раз."""
    g = df[df.track_id.isin(cashier)].sort_values("t")
    g = g[g.t <= g.t.min() + cfg["search_sec"]]
    if g.empty:
        return None
    best, best_motion = g, None
    for t_start in g.t.unique():
        w = g[(g.t >= t_start) & (g.t <= t_start + cfg["init_sec"])]
        if w.t.max() - w.t.min() < cfg["init_sec"] * 0.8 and best_motion is not None:
            break  # дальше окна только короче — хуже по покрытию
        m = _motion(w)
        if best_motion is None or m < best_motion:
            best, best_motion = w, m
    med = tuple(float(np.median(best[c])) for c in ("x1", "y1", "x2", "y2"))
    return expand_box(med, cfg["expand"], width, height)


# ----------------------------------------------------------------- события ---

def build_events(df: pd.DataFrame, meta: dict, cfg: dict) -> dict:
    times: list[float] = meta["frame_times"]
    confirmed = confirmed_tracks(df, cfg["tracks"]["min_track_score"])
    first = pick_cashier(df, times, confirmed, cfg["cashier"])
    if first is None:
        return {"cashier_tracks": [], "zone": None, "events": [], "occupancy": []}
    cashier = cashier_tracks(df, first, cfg["cashier"])
    zone = workplace_zone(df, cashier, meta["width"], meta["height"], cfg["zone"])
    if zone is None:
        return {"cashier_tracks": sorted(cashier), "zone": None, "events": [], "occupancy": []}

    by_t = {t: g for t, g in df[df.track_id.isin(confirmed | cashier)].groupby("t")}
    occupants: list[list[int]] = []
    for t in times:
        g = by_t.get(t)
        ids = [] if g is None else [int(r.track_id) for r in g.itertuples()
                                    if in_zone((r.x1, r.y1, r.x2, r.y2), zone, cfg["zone"]["iou_threshold"])]
        occupants.append(ids)
    raw = [bool(ids) for ids in occupants]
    ev = cfg["events"]
    smooth = fill_gaps(raw, times, ev["fill_gap_sec"])

    events = []
    for start, end in find_absences(smooth, times, ev["min_absence_sec"], ev["min_presence_sec"], ev["end_absence_sec"]):
        events.append({"type": "departure", "t": times[start]})
        if end is None:
            continue
        # кто первым занял зону после отсутствия: кассир (или его продолжение) — return, иначе intrusion
        entrants = occupants[end]
        if any(tid in cashier for tid in entrants):
            events.append({"type": "return", "t": times[end]})
            continue
        tid = entrants[0] if entrants else None
        stay = [times[k] for k in range(end, len(times)) if tid in occupants[k]]
        if stay and stay[-1] - stay[0] >= cfg["events"]["intrusion_min_sec"]:
            events.append({"type": "intrusion", "t": times[end], "track_id": tid})
        else:
            events.append({"type": "return", "t": times[end]})
    # entry: в кадре появился новый подтверждённый человек (не кассир) — не в первом кадре ролика
    for tid, g in df[df.track_id.isin(confirmed - cashier)].groupby("track_id"):
        t_in, t_out = float(g.t.min()), float(g.t.max())
        if t_in > times[0] + ev["entry_after_sec"] and t_out - t_in >= ev["entry_min_sec"]:
            events.append({"type": "entry", "t": t_in, "track_id": int(tid)})
    events.sort(key=lambda e: e["t"])
    return {
        "cashier_tracks": sorted(cashier),
        "zone": [round(v, 1) for v in zone],
        "events": events,
        "occupancy": [[t, int(r), int(s)] for t, r, s in zip(times, raw, smooth)],
    }


def detect_events(video: Path, cfg: dict | None = None, tracks: tuple[pd.DataFrame, dict] | None = None) -> dict:
    """Треки -> события; кэш data/cache/{video}/events.json (пересчитывается всегда: это дёшево)."""
    from . import tracking

    cfg = cfg or load_config()
    df, meta = tracks or tracking.track_video(video, cfg)
    result = {"video": video_key(video), **build_events(df, meta, cfg)}
    (cache_dir(video) / "events.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
