"""Этап 3: события трекинга против разметки.

    python scripts/eval_departures.py [--labels data/labels.xlsx] [--videos-dir data/videos] [--only X-20 X-26]

Для роликов с нарушением: ближайшее к timecode_sec событие departure/intrusion (как в ТЗ модуля)
и отдельно ближайшее entry (вошёл другой человек — кандидат для «дверь открыта / посторонний»).
Сводка: медиана и максимум |delta|, сколько роликов без события. Для роликов без нарушения —
все найденные события (кассир может уходить правильно, но картину надо видеть).
Треки берутся из кэша data/cache/{video}/tracks.parquet; если кэша нет — считаются (нужен детектор).
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import ROOT, events, load_config, tracking  # noqa: E402

_detector = None


def find_video(folder: Path, name: str) -> Path | None:
    for cand in (name, name.replace("X", "Х"), name.replace("Х", "X")):
        if (folder / f"{cand}.mov").exists():
            return folder / f"{cand}.mov"
    return None


def get_tracks(video: Path, cfg: dict):
    global _detector
    if (hit := tracking.cached_tracks(video, cfg)) is not None:
        return hit
    if _detector is None:
        d = cfg["detector"]
        _detector = tracking.PersonDetector(d["model"], d["score_threshold"], d["device"])
    return tracking.track_video(video, cfg, _detector, force=True)


def load_labels(path: Path) -> list[dict]:
    import openpyxl

    ws = openpyxl.load_workbook(path, data_only=True)["labels"]
    rows = list(ws.iter_rows(values_only=True))
    head = [str(h).strip() for h in rows[0]]
    out = []
    for row in rows[1:]:
        r = dict(zip(head, row))
        if r.get("video"):
            out.append({"video": str(r["video"]).strip().replace("Х", "X"),
                        "violation": str(r.get("is_violation")) == "1",
                        "t": float(r["timecode_sec"]) if r.get("timecode_sec") is not None else None,
                        "what": str(r.get("what_happens") or "")})
    return out


def nearest(evs: list[dict], types: tuple[str, ...], t: float) -> dict | None:
    cands = [e for e in evs if e["type"] in types]
    return min(cands, key=lambda e: abs(e["t"] - t)) if cands else None


def fmt(e: dict | None, t: float) -> str:
    return f"{e['type']:9s} {e['t']:5.1f} {e['t'] - t:+5.1f}" if e else f"{'-':9s} {'':5s} {'':5s}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, default=ROOT / "data" / "labels.xlsx")
    ap.add_argument("--videos-dir", type=Path, default=ROOT / "data" / "videos")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()

    cfg = load_config()
    labels = load_labels(args.labels)
    if args.only:
        only = {o.replace("Х", "X") for o in args.only}
        labels = [lab for lab in labels if lab["video"] in only]

    viol_rows, clean_rows, deltas, deltas_entry, missing = [], [], [], [], []
    for lab in sorted(labels, key=lambda r: int("".join(c for c in r["video"] if c.isdigit()) or 0)):
        video = find_video(args.videos_dir, lab["video"])
        if video is None:
            print(f"{lab['video']}: нет файла ролика", file=sys.stderr)
            continue
        res = events.detect_events(video, cfg, get_tracks(video, cfg))
        evs = res["events"]
        if lab["violation"] and lab["t"] is not None:
            d = nearest(evs, ("departure", "intrusion"), lab["t"])
            e = nearest(evs, ("entry",), lab["t"])
            if d:
                deltas.append(abs(d["t"] - lab["t"]))
            if e:
                deltas_entry.append(abs(e["t"] - lab["t"]))
            if not d and not e:
                missing.append(lab["video"])
            viol_rows.append(f"{lab['video']:5s} {lab['t']:5.0f}  {fmt(d, lab['t'])}  | {fmt(e, lab['t'])}  | "
                             f"{lab['what'][:60]}")
        else:
            found = ", ".join(f"{x['type']}@{x['t']:.1f}" for x in evs) or "-"
            clean_rows.append(f"{lab['video']:5s} {found}")

    print("Ролики с нарушением: ближайшее событие к метке (delta = событие − метка, с)")
    print(f"{'video':5s} {'label':>5s}  {'departure/intrusion':25s}  | {'entry':25s}  | что происходит")
    print("\n".join(viol_rows))
    n = len(viol_rows)
    if deltas:
        print(f"\ndeparture/intrusion: найдено в {len(deltas)}/{n}, |delta| медиана {statistics.median(deltas):.1f} с, "
              f"макс {max(deltas):.1f} с, в пределах ±2 с: {sum(d <= 2 for d in deltas)}")
    if deltas_entry:
        print(f"entry: найдено в {len(deltas_entry)}/{n}, |delta| медиана {statistics.median(deltas_entry):.1f} с, "
              f"макс {max(deltas_entry):.1f} с, в пределах ±2 с: {sum(d <= 2 for d in deltas_entry)}")
    print(f"роликов с нарушением без единого события: {len(missing)} ({', '.join(missing) or '-'})")
    print("\nРолики без нарушения: найденные события")
    print("\n".join(clean_rows))


if __name__ == "__main__":
    main()
