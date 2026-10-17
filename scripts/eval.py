"""Прогон датасета через пайплайн и сверка с разметкой.

    python scripts/eval.py VIDEOS_DIR LABELS.xlsx --out eval_out            # полный прогон (модель)
    python scripts/eval.py VIDEOS_DIR LABELS.xlsx --out eval_out --rescore  # только правила, без модели

Полный прогон сохраняет шкалу ответов модели по каждому видео (eval_out/<имя>.json);
--rescore перечитывает их и заново применяет rules.json — так правила подбираются за секунды.
Таймкод засчитывается, если событие попало в ±TOL секунд от метки.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, pipeline, rules as rule_engine  # noqa: E402

TOL = 2.0


def norm(name: str) -> str:
    return name.replace("X", "Х")  # латинская X -> кириллическая Х


def parse_t(s) -> float | None:
    if not s:
        return None
    m = re.search(r"(\d+)\s*мин", str(s))
    sec = re.search(r"(\d+)\s*сек", str(s))
    return (int(m.group(1)) * 60 if m else 0) + (int(sec.group(1)) if sec else 0)


def load_labels(path: Path) -> dict:
    import openpyxl

    ws = openpyxl.load_workbook(path, data_only=True).active
    labels = {}
    for row in list(ws.iter_rows(values_only=True))[1:]:
        if not row or not row[0]:
            continue
        name, ts, verdict = row[:3]
        lab = labels.setdefault(norm(str(name).strip()), {"times": [], "violation": False})
        lab["violation"] |= str(verdict).strip() == "нарушение"
        if parse_t(ts) is not None:
            lab["times"].append(parse_t(ts))
    return labels


def score(labels: dict, results: dict) -> None:
    tp = fp = fn = tn = loc = 0
    rows = []
    for name in sorted(results, key=lambda n: int(re.sub(r"\D", "", n) or 0)):
        res, lab = results[name], labels.get(name)
        if lab is None:
            continue
        pred = res["verdict"] == "violation"
        ev = [(v["timecode_sec"], v["type"]) for v in res["violations"]]
        hit = any(abs(t - lt) <= TOL for t, _ in ev for lt in lab["times"])
        if lab["violation"] and pred:
            tp += 1
            loc += hit
        elif lab["violation"]:
            fn += 1
        elif pred:
            fp += 1
        else:
            tn += 1
        mark = ("OK " if pred == lab["violation"] else "ERR") + (" loc" if hit else "    ")
        rows.append(f"{mark} {name:6s} label={'V@' + ','.join(map(str, lab['times'])) if lab['violation'] else 'clean':10s} "
                    f"pred={'; '.join(f'{t:.0f}s {ty}' for t, ty in ev) or '-'}")
    print("\n".join(rows))
    n = tp + fp + fn + tn
    print(f"\nвердикт: верно {tp + tn}/{n}  | пропуски {fn}  | ложные {fp}  | "
          f"таймкод ±{TOL:.0f}с у верных нарушений: {loc}/{tp}")


def make_live_writer(path: Path, name: str, label: dict | None, cfg: dict, done: int, total: int):
    """Колбэк для pipeline.analyze_video: после каждого кадра перезаписывает path
    (атомарно, через временный файл), его читает scripts/live.html."""
    rows: list[dict] = []
    probes = [{"id": p["id"], "title": p.get("title", p["id"])} for p in cfg["probes"]]

    def write(row: dict, preview: bytes) -> None:
        rows.append({"t": row["t"], "a": row["a"]})
        rows.sort(key=lambda r: r["t"])
        events = rule_engine.evaluate(rows, cfg["rules"], config.MERGE_GAP_SEC, config.MAX_EVENTS_PER_RULE)
        state = {
            "video": name, "index": done + 1, "total": total,
            "label": label, "probes": probes, "rows": rows, "preview_t": row["t"],
            "preview": base64.b64encode(preview).decode(),
            "events": [{"t": round(e.t, 1), "type": e.rule["type"]} for e in events],
            "updated": time.time(),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False))
        tmp.replace(path)

    return write


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", type=Path)
    ap.add_argument("labels", type=Path)
    ap.add_argument("--out", type=Path, default=Path("eval_out"))
    ap.add_argument("--rules", type=Path, default=None)
    ap.add_argument("--only", nargs="*", help="имена видео без расширения, например Х-20 X-2")
    ap.add_argument("--rescore", action="store_true", help="не вызывать модель, применить правила к сохранённым шкалам")
    ap.add_argument("--skip-done", action="store_true", help="пропустить видео, для которых уже есть результат в --out")
    ap.add_argument("--live", type=Path, default=None,
                    help="писать сюда JSON живого просмотра (кадр, ответы, события) после каждого кадра")
    args = ap.parse_args()

    labels = load_labels(args.labels)
    args.out.mkdir(parents=True, exist_ok=True)
    cfg = pipeline.load_rules(args.rules)
    results = {}
    videos = sorted(args.videos.glob("*.mov"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
    only = {norm(o) for o in args.only} if args.only else None
    for video in videos:
        name = norm(video.stem)
        if only and name not in only:
            continue
        saved = args.out / f"{name}.json"
        if args.rescore:
            if not saved.exists():
                continue
            dbg = json.loads(saved.read_text())["_debug"]
            events = rule_engine.evaluate(dbg["timeline"], cfg["rules"], config.MERGE_GAP_SEC, config.MAX_EVENTS_PER_RULE)
            results[name] = {"verdict": "violation" if events else "no_violation",
                             "violations": [{"timecode_sec": round(e.t, 1), "type": e.rule["type"]} for e in events]}
            continue
        if args.skip_done and saved.exists():
            results[name] = json.loads(saved.read_text())
            continue
        t0 = time.monotonic()
        on_frame = make_live_writer(args.live, name, labels.get(name), cfg, done=len(results), total=len(videos)) \
            if args.live else None
        res = pipeline.analyze_video(name, video, rules_path=args.rules, on_frame=on_frame)
        elapsed = time.monotonic() - t0
        for v in res["violations"]:
            v["evidence_frames"] = f"<{len(v['evidence_frames'])} frames>"
        res["_debug"]["seconds"] = round(elapsed, 1)
        saved.write_text(json.dumps(res, ensure_ascii=False, indent=1))
        results[name] = res
        d = res["_debug"]
        print(f"{name}: {res['verdict']} {elapsed:.0f}s frames {d['frames_analyzed']}/{d['frames_total']} "
              f"zones={d['zones'].get('found')}", flush=True)
    score(labels, results)


if __name__ == "__main__":
    main()
