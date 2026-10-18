"""Пересчёт правил main по сохранённым ответам модели с фильтром по трекингу.

    python scripts/rescore_tracking_gate.py EVAL_DIR LABELS.xlsx [--tracking-vlm data/debug/tracking_vlm.json]

EVAL_DIR — сохранённые прогоны scripts/eval.py (например eval_30b_v2/), LABELS — open_labels.xlsx.
Варианты (метрики считает score() из scripts/eval.py, те же, что в docs/run_review.md):
  main    — правила как есть (= eval.py --rescore);
  gate    — правило экрана (screen_unlocked_absent) срабатывает, только если трекинг нашёл
            departure в окне [событие − BEFORE, событие + AFTER] (data/cache/{видео}/events.json);
  gate+tv — gate плюс нарушения связки «уход -> Qwen» (scripts/eval_tracking_vlm.py), если файл есть.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config, pipeline as app_pipeline, rules as rule_engine  # noqa: E402
from eval import load_labels, load_types, rule_ids_by_type_text, score  # noqa: E402
from pipeline import CACHE_DIR  # noqa: E402

GATED_RULES = {"screen_unlocked_absent"}
BEFORE, AFTER = 3.0, 6.0  # уход по трекингу наступает позже, чем кассир встаёт из-за стола


def departures(name: str) -> list[float] | None:
    path = CACHE_DIR / name.replace("Х", "X") / "events.json"
    if not path.exists():
        return None
    return [e["t"] for e in json.loads(path.read_text())["events"] if e["type"] == "departure"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("eval_dir", type=Path)
    ap.add_argument("labels", type=Path)
    ap.add_argument("--rules", type=Path, default=None)
    ap.add_argument("--tracking-vlm", type=Path, default=Path("data/debug/tracking_vlm.json"))
    ap.add_argument("--types", type=Path, default=Path(__file__).resolve().parent.parent / "docs" / "labels_types.csv")
    args = ap.parse_args()

    labels = load_labels(args.labels)
    cfg = app_pipeline.load_rules(args.rules)
    tv = json.loads(args.tracking_vlm.read_text()) if args.tracking_vlm.exists() else {}
    variants: dict[str, dict] = {"main": {}, "gate": {}, "gate+tv": {}}
    changed = []
    for saved in sorted(args.eval_dir.glob("*.json"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0)):
        name = saved.stem
        dbg = json.loads(saved.read_text())["_debug"]
        events = rule_engine.evaluate(dbg["timeline"], cfg["rules"], config.MERGE_GAP_SEC,
                                      config.MAX_EVENTS_PER_RULE, dbg.get("signals"))
        deps = departures(name)
        kept = [e for e in events if e.rule["id"] not in GATED_RULES or deps is None
                or any(e.t - BEFORE <= d <= e.t + AFTER for d in deps)]
        for key, evs in (("main", events), ("gate", kept)):
            variants[key][name] = {"verdict": "violation" if evs else "no_violation",
                                   "violations": [{"timecode_sec": round(e.t, 1), "type": e.rule["type"]} for e in evs]}
        extra = (tv.get(name.replace("Х", "X")) or {}).get("pred")
        res = variants["gate"][name]
        added = bool(extra) and res["verdict"] == "no_violation"
        if added:
            res = {"verdict": "violation", "violations": [{"timecode_sec": extra[1], "type": extra[0]}]}
        variants["gate+tv"][name] = res
        if len(kept) != len(events) or added:
            changed.append(f"{name}: main {[e.rule['id'] for e in events]} -> gate {[e.rule['id'] for e in kept]}"
                           + (f" + трекинг {extra[0]}@{extra[1]}" if added else "")
                           + ("" if deps is not None else " (нет events.json — фильтр не применён)"))
    all_rules = json.loads((args.rules or config.RULES_PATH).read_text(encoding="utf-8"))["rules"]
    for key, results in variants.items():
        print(f"\n===== {key} =====")
        score(labels, results, load_types(args.types), rule_ids_by_type_text({"rules": all_rules}))
    print("\nИзменения относительно main:\n" + ("\n".join(changed) or "-"))


if __name__ == "__main__":
    main()
