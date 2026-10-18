"""Этап 1: насколько стабильно RT-DETR видит людей сверху.

    python scripts/debug_detections.py X-20 X-26 X-30 [--n 10] [--out data/debug]

По каждому ролику: 10 равномерно взятых кадров с рамками (data/debug/<видео>/), кадры, где
число людей упало по сравнению с соседями (data/debug/<видео>/drops/), и статистика: сколько
кадров без людей, распределение числа людей, шкала по времени, скорость детектора.
Кадры датасета: только локально, не публиковать.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import ROOT, load_config, tracking  # noqa: E402


def find_video(folder: Path, name: str) -> Path:
    for cand in (name, name.replace("X", "Х"), name.replace("Х", "X")):
        if (folder / f"{cand}.mov").exists():
            return folder / f"{cand}.mov"
    raise FileNotFoundError(f"Нет ролика {name}.mov в {folder}")


def draw(frame: np.ndarray, dets: np.ndarray, t: float) -> np.ndarray:
    img = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    for x1, y1, x2, y2, s in dets:
        color = (0, 200, 0) if s >= 0.5 else (0, 200, 255)  # зелёный — уверенная, оранжевый — слабая
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
        cv2.putText(img, f"{s:.2f}", (int(x1) + 3, int(y1) + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    cv2.putText(img, f"t={t:.2f}s people={len(dets)}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--videos-dir", type=Path, default=ROOT / "data" / "videos")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "debug")
    ap.add_argument("--n", type=int, default=10)
    args = ap.parse_args()

    cfg = load_config()
    det_cfg = cfg["detector"]
    t0 = time.perf_counter()
    detector = tracking.PersonDetector(det_cfg["model"], det_cfg["score_threshold"], det_cfg["device"])
    print(f"детектор {det_cfg['model']} на {detector.device}, загрузка {time.perf_counter() - t0:.1f} с")

    for name in args.videos:
        video = find_video(args.videos_dir, name)
        out = args.out / name.replace("Х", "X")
        (out / "drops").mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        rows = list(tracking.detect_video(video, cfg, detector, keep_frames=True))
        sec = time.perf_counter() - t0
        counts = [len(d) for _, d, _ in rows]
        strong = [int((d[:, 4] >= 0.5).sum()) for _, d, _ in rows]
        top = [float(d[:, 4].max()) for _, d, _ in rows if len(d)]

        for i in np.linspace(0, len(rows) - 1, args.n).round().astype(int):
            t, d, f = rows[i]
            cv2.imwrite(str(out / f"{t:06.2f}.jpg"), draw(f, d, t))
        # «провал»: людей меньше, чем на обоих соседних кадрах
        drops = [i for i in range(1, len(rows) - 1) if counts[i] < counts[i - 1] and counts[i] < counts[i + 1]]
        for i in drops[:12]:
            t, d, f = rows[i]
            cv2.imwrite(str(out / "drops" / f"{t:06.2f}.jpg"), draw(f, d, t))

        print(f"\n== {name}: {len(rows)} кадров за {rows[-1][0]:.1f} с, детекция {sec:.1f} с "
              f"({sec / len(rows) * 1000:.0f} мс/кадр)")
        print(f"   людей на кадре (score≥{det_cfg['score_threshold']}): {dict(sorted(Counter(counts).items()))}; "
              f"уверенных (≥0.5): {dict(sorted(Counter(strong).items()))}")
        print(f"   кадров без людей: {counts.count(0)}; одиночных провалов: {len(drops)} "
              f"({', '.join(f'{rows[i][0]:.1f}' for i in drops[:12]) or '-'})")
        if top:
            print(f"   макс. score на кадре: медиана {np.median(top):.2f}, мин {min(top):.2f}")
        print("   шкала (число людей, кадр = 0,2 с):", "".join(str(min(c, 9)) for c in counts))


if __name__ == "__main__":
    main()
