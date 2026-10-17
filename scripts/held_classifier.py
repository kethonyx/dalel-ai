"""Классификатор «что в руках»: SigLIP-признаки + логистическая регрессия.

    python scripts/held_classifier.py extract OWN_DIR DATASET_DIR   # кропы (нужна VLM для поиска зоны)
    python scripts/held_classifier.py train                          # признаки SigLIP, обучение, отчёт
    python scripts/held_classifier.py vlm                            # ответы VLM на тех же тестовых кадрах

Обучение — только на своих роликах (блок 1 docs/shooting_plan.md, разметка в имени файла).
Проверка — на кадрах датасета организаторов, где ответ проверен вручную: другой ракурс и
другие люди, классификатор их не видел. Кадры своих роликов уменьшаются до 848 px по длинной
стороне — как в датасете, чтобы предметы были такими же мелкими.
Кропы лежат в data/held/ (кадры датасета: только локально, в git не попадают).
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import pipeline, vlm  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "held"
CLASSES = ["nothing", "banknotes", "id_card", "cash_bag", "phone", "other"]
PREFIX = {  # префикс имени файла своего ролика -> класс
    "id_client": "id_card", "id_cashier": "id_card", "id_desk": "id_card",
    "cash_hand": "banknotes", "cash_count": "banknotes", "cash_machine": "banknotes", "cash_desk": "banknotes",
    "bag_hand": "cash_bag", "nothing": "nothing", "phone": "phone", "paper": "other", "bankcard": "other",
}
# кадры датасета с ответом, проверенным вручную по крупным кадрам (docs/dataset_notes.md)
TESTS = [
    ("Х-3.mov", 4.0, {"nothing"}), ("Х-3.mov", 8.0, {"id_card"}), ("Х-3.mov", 10.0, {"id_card"}),
    ("Х-3.mov", 12.0, {"banknotes"}), ("Х-3.mov", 15.0, {"banknotes"}),
    ("X-2.mov", 5.0, {"nothing"}), ("X-2.mov", 9.5, {"banknotes"}), ("X-2.mov", 10.5, {"banknotes"}),
    ("X-2.mov", 12.5, {"banknotes"}),
    ("X-1.mov", 7.0, {"id_card"}), ("X-1.mov", 10.0, {"banknotes"}), ("X-1.mov", 12.0, {"banknotes"}),
    ("Х-16.mov", 9.9, {"id_card"}), ("Х-16.mov", 12.8, {"id_card", "cash_bag"}),
    ("Х-16.mov", 15.6, {"cash_bag"}), ("Х-16.mov", 18.5, {"cash_bag"}),
    ("Х-17.mov", 5.5, {"cash_bag"}), ("Х-17.mov", 8.0, {"cash_bag"}),
    ("Х-34.mov", 7.0, {"banknotes"}),
    ("Х-4.mov", 63.0, {"id_card"}), ("Х-4.mov", 66.0, {"banknotes"}),
    ("Х-44.mov", 16.0, {"banknotes"}), ("Х-15.mov", 3.0, {"cash_bag"}), ("Х-15.mov", 5.0, {"cash_bag"}),
]
LABELS = ["cashier desk", "metal safe", "banknote counting machine"]


def duration(p: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 str(p)], capture_output=True, text=True).stdout)


def frame(p: Path, t: float, long_side: int = 848) -> Image.Image:
    """Кадр как в датасете: длинная сторона 848 px (ffmpeg сам учитывает поворот видео)."""
    img = Image.open(io.BytesIO(pipeline.grab_frame_jpeg(p, t, 4000))).convert("RGB")
    s = long_side / max(img.size)
    return img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS) if s < 1 else img


def zones_for(img: Image.Image) -> dict:
    found = vlm.ground(pipeline.to_jpeg(img, 640), LABELS, img.width, img.height)
    boxes = {}
    for b in found:
        boxes.setdefault(b["label"], []).append(b["box"])
    allb = pipeline.union([x for v in boxes.values() for x in v])
    zone = pipeline.pad(allb, 0.15, 0.55, 0.2) if allb else (0.0, 0.0, 1.0, 1.0)
    desk = pipeline.union(boxes.get("cashier desk", []))
    return {"zone": zone, "desk": pipeline.pad(desk, 0.05, 0.6, 0.0) if desk else zone}


def save_crops(img: Image.Image, z: dict, stem: str, split: str, label: str, meta: list) -> None:
    for kind in ("zone", "desk"):
        d = OUT / split / kind
        d.mkdir(parents=True, exist_ok=True)
        pipeline.crop_frac(img, z[kind]).save(d / f"{stem}.jpg", quality=92)
    meta.append({"split": split, "stem": stem, "label": label})


def extract(own: Path, dataset: Path) -> None:
    meta: list[dict] = []
    for p in sorted(own.glob("*.mov")) + sorted(own.glob("*.MOV")):
        m = re.match(r"(.+?)_[A-Z]_\d+$", p.stem)
        if not m or m.group(1) not in PREFIX:
            continue  # сценарии S* и прочее — не для обучения
        label, d = PREFIX[m.group(1)], duration(p)
        z = zones_for(frame(p, d / 2))  # зона одна на ролик: камера неподвижна
        t = d * 0.15
        while t <= d * 0.85:  # середина ролика: действие уже идёт
            save_crops(frame(p, t), z, f"{p.stem}_{t:05.1f}", "train", label, meta)
            t += 0.5
        print(f"{p.name:28s} {label:10s}", flush=True)
    zone_cache: dict[str, dict] = {}
    for f, t, truth in TESTS:
        img = frame(dataset / f, t)
        if f not in zone_cache:
            zone_cache[f] = zones_for(img)
        stem = f"{Path(f).stem}_{t:05.1f}"
        save_crops(img, zone_cache[f], stem, "test", "/".join(sorted(truth)), meta)
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    n = sum(m["split"] == "train" for m in meta)
    print(f"train: {n} кадров, test: {len(meta) - n}")


def embed(paths: list[Path], model, proc, device) -> "np.ndarray":
    import numpy as np
    import torch

    out = []
    for i in range(0, len(paths), 16):
        ims = [Image.open(p).convert("RGB") for p in paths[i:i + 16]]
        with torch.no_grad():
            x = proc(images=ims, return_tensors="pt").to(device)
            e = model.get_image_features(**x)
            e = e.pooler_output if hasattr(e, "pooler_output") else e
            out.append(torch.nn.functional.normalize(e, dim=-1).cpu().numpy())
    return np.concatenate(out)


def train() -> None:
    import numpy as np
    import torch
    from sklearn.linear_model import LogisticRegression
    from transformers import AutoModel, AutoProcessor

    meta = json.loads((OUT / "meta.json").read_text())
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    name = "google/siglip2-base-patch16-384"
    model = AutoModel.from_pretrained(name).to(device).eval()
    proc = AutoProcessor.from_pretrained(name)
    tr = [m for m in meta if m["split"] == "train"]
    te = [m for m in meta if m["split"] == "test"]
    report = {}
    for kind in ("zone", "desk"):
        def feats(rows, split, flip=False):
            paths = [OUT / split / kind / f"{r['stem']}.jpg" for r in rows]
            if not flip:
                return embed(paths, model, proc, device)
            tmp = OUT / "_flip"; tmp.mkdir(exist_ok=True)
            fl = []
            for p in paths:
                q = tmp / p.name; Image.open(p).transpose(Image.FLIP_LEFT_RIGHT).save(q); fl.append(q)
            return embed(fl, model, proc, device)
        Xtr = np.concatenate([feats(tr, "train"), feats(tr, "train", flip=True)])  # + отзеркаливание
        ytr = [r["label"] for r in tr] * 2
        Xte = feats(te, "test")
        clf = LogisticRegression(max_iter=3000, C=2.0, class_weight="balanced").fit(Xtr, ytr)
        pred = clf.predict(Xte)
        ok = [p in r["label"].split("/") for p, r in zip(pred, te)]
        # zero-shot SigLIP по текстовым описаниям — без обучения, для сравнения
        texts = {"nothing": "empty hands resting on a desk", "banknotes": "a hand holding banknotes, paper money",
                 "id_card": "a hand holding a small plastic ID card", "cash_bag": "a green cash-collection bag",
                 "phone": "a hand holding a smartphone", "other": "a sheet of white paper or a bank card"}
        with torch.no_grad():
            tx = proc(text=list(texts.values()), return_tensors="pt", padding="max_length").to(device)
            te_emb = model.get_text_features(**tx)
            te_emb = te_emb.pooler_output if hasattr(te_emb, "pooler_output") else te_emb
            te_emb = torch.nn.functional.normalize(te_emb, dim=-1).cpu().numpy()
        zs = [list(texts)[i] for i in (Xte @ te_emb.T).argmax(1)]
        zs_ok = [p in r["label"].split("/") for p, r in zip(zs, te)]
        report[kind] = {"classifier": sum(ok), "zero_shot": sum(zs_ok), "n": len(te),
                        "rows": [(r["stem"], r["label"], p, z) for r, p, z in zip(te, pred, zs)]}
        print(f"\n== кроп {kind}: классификатор {sum(ok)}/{len(te)}, SigLIP zero-shot {sum(zs_ok)}/{len(te)}")
        for (stem, lab, p, z), o in zip(report[kind]["rows"], ok):
            print(f"  {'✓' if o else '✗'} {stem:14s} истина={lab:17s} классификатор={p:10s} zero-shot={z}")
        import pickle
        (OUT / f"clf_{kind}.pkl").write_bytes(pickle.dumps(clf))
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))


def vlm_answers() -> None:
    """Ответ VLM (вопрос held_object из rules.json) на тех же тестовых кропах."""
    cfg = pipeline.load_rules()
    pr = next(p for p in cfg["probes"] if p["id"] == "held_object")
    meta = [m for m in json.loads((OUT / "meta.json").read_text()) if m["split"] == "test"]
    for kind in ("zone", "desk"):
        ok = 0
        print(f"\n== VLM ({vlm.model_id().split('/')[-1]}), кроп {kind}")
        for r in meta:
            img = Image.open(OUT / "test" / kind / f"{r['stem']}.jpg").convert("RGB")
            a = vlm.ask_choice(pipeline.to_jpeg(img, 640), pr["question"], pr["options"])["answer"]
            hit = a in r["label"].split("/"); ok += hit
            print(f"  {'✓' if hit else '✗'} {r['stem']:14s} истина={r['label']:17s} VLM={a}")
        print(f"VLM кроп {kind}: {ok}/{len(meta)}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "extract":
        extract(Path(sys.argv[2]), Path(sys.argv[3]))
    elif cmd == "train":
        train()
    elif cmd == "vlm":
        vlm_answers()
