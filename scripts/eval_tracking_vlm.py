"""Быстрая оценка связки «трекинг -> Qwen» на всех роликах.

    python scripts/eval_tracking_vlm.py [--base-url http://gn04:8080/v1] [--only X-24 X-26]

На каждом departure из events.json: кадры через 1 и 2 с после ухода, кроп вокруг рабочего места
(зона трекинга, расширенная), четыре узких вопроса yes/no. Нарушение — если на обоих кадрах «да»
хотя бы на один вопрос. Это только типы «ушёл и оставил»: сценарии с клиентом, дверь и X-20
(сейф при кассире) здесь не проверяются — их закрывают правила основного пайплайна.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config as app_config, vlm  # noqa: E402
from eval_departures import find_video, load_labels  # noqa: E402
from pipeline import ROOT, events, load_config, tracking  # noqa: E402

QUESTIONS = [  # (тип, вопрос); порядок = приоритет типа
    ("cash_unattended", "Are banknotes or bundles of cash lying on the desk, not held in anyone's hands?"),
    ("safe_left_open", "Is the door of the grey metal safe (cabinet) open?"),
    ("work_items_left", "Apart from the equipment that always stays on the desk (laptop, phone, printer, counting "
                        "machine, cables), is a tablet, documents, a stamp or a folder lying on the desk?"),
    ("workstation_unlocked", "Does the laptop screen show a document or spreadsheet with text or tables? "
                             "A full-screen photo or wallpaper means a lock screen."),
]
CROP_EXPAND = 2.2  # зона трекинга (1,5× рамки кассира) мала для стола и сейфа рядом


def crop_jpeg(video: Path, t: float, zone: list[float]) -> bytes | None:
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = (int(v) for v in events.expand_box(tuple(zone), CROP_EXPAND / 1.5, w, h))
    crop = frame[y1:y2, x1:x2]
    s = 640 / max(crop.shape[:2])
    crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    return cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path, default=ROOT / "data" / "labels.xlsx")
    ap.add_argument("--videos-dir", type=Path, default=ROOT / "data" / "videos")
    ap.add_argument("--base-url", default=app_config.VLM_BASE_URL)
    ap.add_argument("--api-key", default=app_config.VLM_API_KEY)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()

    cfg = load_config()
    backend = vlm.OpenAILocalBackend(args.base_url, "local", 120, args.api_key)
    labels = load_labels(args.labels)
    if args.only:
        labels = [lab for lab in labels if lab["video"] in set(args.only)]
    rows, out = [], {}
    for lab in sorted(labels, key=lambda r: int("".join(c for c in r["video"] if c.isdigit()) or 0)):
        video = find_video(args.videos_dir, lab["video"])
        hit = tracking.cached_tracks(video, cfg)
        if hit is None:
            print(f"{lab['video']}: нет кэша треков (сначала eval_departures.py на GPU)", file=sys.stderr)
            continue
        res = events.detect_events(video, cfg, hit)
        found = None
        detail = []
        for ev in [e for e in res["events"] if e["type"] == "departure"]:
            frames = [crop_jpeg(video, ev["t"] + dt, res["zone"]) for dt in (1.0, 2.0)]
            frames = [f for f in frames if f]
            if not frames:
                continue
            answers = {qid: [backend.ask(f, q)["answer"] for f in frames] for qid, q in QUESTIONS}
            detail.append({"t": ev["t"], "answers": answers})
            yes = [qid for qid, a in answers.items() if all(x == "yes" for x in a)]
            if yes and found is None:
                found = (yes[0], ev["t"])
        pred = found is not None
        out[lab["video"]] = {"label": lab, "pred": found, "departures": detail}
        mark = "OK " if pred == lab["violation"] else ("FN " if lab["violation"] else "FP ")
        lt = f"{lab['t']:.0f}" if lab["t"] is not None else "-"
        rows.append(f"{mark} {lab['video']:5s} {'нарушение@' + lt if lab['violation'] else 'чисто':14s} "
                    f"{(found[0] + '@' + str(found[1])) if found else '-':30s} уходов {len(detail)}")
        print(rows[-1], flush=True)
    viol = [v for v in out.values() if v["label"]["violation"]]
    clean = [v for v in out.values() if not v["label"]["violation"]]
    tp = sum(v["pred"] is not None for v in viol)
    fp = sum(v["pred"] is not None for v in clean)
    print(f"\nнайдено нарушений {tp}/{len(viol)}, ложных на чистых {fp}/{len(clean)}, "
          f"верный вердикт {tp + len(clean) - fp}/{len(out)} (только типы «ушёл и оставил»)")
    (ROOT / "data" / "debug").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "debug" / "tracking_vlm.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
