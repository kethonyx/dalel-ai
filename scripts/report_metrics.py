"""Метрики для отчёта по сохранённому прогону scripts/eval.py (markdown в stdout).

    python scripts/report_metrics.py EVAL_DIR LABELS.xlsx [--types docs/labels_types.csv]

Вердикт: TP / FP / TN / FN, accuracy, recall и precision по нарушениям. Таймкод: для верно найденных
нарушений — |ближайший таймкод ответа − метка|, медиана и максимум. Тип: та же логика, что в
scripts/eval.py (тип из docs/labels_types.csv совпал с правилом хотя бы одного события).
Время: _debug.seconds — время pipeline.analyze_video на ролик в этом прогоне.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config  # noqa: E402
from eval import TYPE_RULES, load_labels, load_types, rule_ids_by_type_text  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("eval_dir", type=Path)
    ap.add_argument("labels", type=Path)
    ap.add_argument("--types", type=Path, default=Path(__file__).resolve().parent.parent / "docs" / "labels_types.csv")
    ap.add_argument("--rules", type=Path, default=None)
    args = ap.parse_args()

    labels = load_labels(args.labels)
    types = load_types(args.types)
    all_rules = json.loads((args.rules or config.RULES_PATH).read_text(encoding="utf-8"))["rules"]
    type_ids = rule_ids_by_type_text({"rules": all_rules})
    tp = fp = tn = fn = 0
    tc_err, type_ok, type_n, secs, rows = [], 0, 0, [], []
    files = sorted(args.eval_dir.glob("*.json"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
    for f in files:
        name = f.stem
        lab = labels.get(name)
        if lab is None:
            continue
        res = json.loads(f.read_text())
        dbg = res.get("_debug", {})
        secs.append((name, dbg.get("seconds"), dbg.get("duration"), dbg.get("frames_analyzed"), dbg.get("frames_total")))
        ev = [(v["timecode_sec"], v["type"]) for v in res["violations"]]
        pred = res["verdict"] == "violation"
        err = None
        if lab["violation"] and pred:
            tp += 1
            err = min(abs(t - lt) for t, _ in ev for lt in lab["times"]) if ev and lab["times"] else None
            if err is not None:
                tc_err.append(err)
        elif lab["violation"]:
            fn += 1
        elif pred:
            fp += 1
        else:
            tn += 1
        t_mark = "—"
        if lab["violation"] and name in types:
            got = set().union(*[type_ids.get(ty, set()) for _, ty in ev]) if ev else set()
            ok_t = bool(TYPE_RULES.get(types[name], set()) & got)
            type_n += 1
            type_ok += ok_t
            t_mark = f"{'верно' if ok_t else 'неверно'} ({types[name]})"
        elif lab["violation"]:
            t_mark = "тип в разметке не установлен"
        verdict_ok = pred == lab["violation"]
        label_txt = f"нарушение @{', '.join(f'{t:g}' for t in lab['times'])} с" if lab["violation"] else "чисто"
        pred_txt = "; ".join(f"{t:g} с {ty}" for t, ty in ev) or "нет нарушений"
        rows.append(f"| {name} | {label_txt} | {pred_txt} | {f'{err:.1f}' if err is not None else '—'} | {t_mark} | "
                    f"{'верно' if verdict_ok else ('**пропуск**' if lab['violation'] else '**ложное**')} |")
    n = tp + fp + tn + fn
    print(f"Роликов: {n}. TP {tp}, FP {fp}, TN {tn}, FN {fn}. Accuracy {(tp + tn) / n:.1%} ({tp + tn}/{n}), "
          f"recall {tp / (tp + fn):.1%} ({tp}/{tp + fn}), precision {tp / (tp + fp):.1%} ({tp}/{tp + fp}).")
    if tc_err:
        print(f"Таймкод (верно найденные нарушения, {len(tc_err)}): |ошибка| медиана {statistics.median(tc_err):.1f} с, "
              f"максимум {max(tc_err):.1f} с, в пределах ±2 с: {sum(e <= 2 for e in tc_err)}/{len(tc_err)}.")
    print(f"Тип: верно {type_ok}/{type_n} (ролики с нарушением и известным типом).")
    s = [x[1] for x in secs if x[1] is not None]
    if s:
        longest = max(secs, key=lambda x: x[2] or 0)
        print(f"Время analyze_video: медиана {statistics.median(s):.0f} с, максимум {max(s):.0f} с; самый длинный ролик "
              f"{longest[0]} ({longest[2]:.0f} с видео): {longest[1]:.0f} с, кадров {longest[3]}/{longest[4]}.")
    print("\n| Ролик | Разметка | Ответ сервиса | Ошибка таймкода, с | Тип | Вердикт |\n|---|---|---|---|---|---|")
    print("\n".join(rows))


if __name__ == "__main__":
    main()
