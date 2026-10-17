"""Наглядно: что модель видела и что ответила по каждому кадру.

    python scripts/debug_view.py VIDEO eval_out/<имя>.json [--label 10] [--out view.html]

Берёт шкалу ответов, сохранённую scripts/eval.py, вырезает те же кадры и кропы, что
получала модель, и собирает один HTML-файл: сетка «вопрос × кадр» (зелёный = yes),
по клику на кадр — полный кадр с рамками зон и кроп рабочей зоны.
Файл содержит кадры датасета: только для локального просмотра, не публиковать.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import pipeline  # noqa: E402


def b64(img: Image.Image, side: int) -> str:
    return base64.b64encode(pipeline.to_jpeg(img, side)).decode()


def draw_boxes(img: Image.Image, zones: dict) -> Image.Image:
    img = img.copy()
    d = ImageDraw.Draw(img)
    W, H = img.size
    for key, color in (("zone", "#2f81f7"), ("safe", "#f0883e")):
        box = zones.get(key)
        if box:
            d.rectangle([box[0] * W, box[1] * H, box[2] * W, box[3] * H], outline=color, width=max(2, W // 160))
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("result", type=Path)
    ap.add_argument("--label", type=float, nargs="*", default=[], help="секунды нарушения из разметки")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--rules", type=Path, default=None)
    args = ap.parse_args()

    res = json.loads(args.result.read_text())
    dbg = res["_debug"]
    timeline, zones = dbg["timeline"], dbg.get("zones") or {}
    cfg = pipeline.load_rules(args.rules)
    probe_ids = [p["id"] for p in cfg["probes"]]
    questions = {p["id"]: p["question"] for p in cfg["probes"]}
    events = [(v["timecode_sec"], v["type"]) for v in res["violations"]]

    frames = []
    for fr in timeline:
        img = Image.open(io.BytesIO(pipeline.grab_frame_jpeg(args.video, fr["t"], 1280))).convert("RGB")
        crop = pipeline.crop_frac(img, tuple(zones["zone"])) if zones.get("zone") else img
        frames.append({"t": fr["t"], "a": fr["a"], "r": fr.get("r", {}),
                       "full": b64(draw_boxes(img, zones), 520), "zone": b64(crop, 640)})

    head = "".join(f'<th class="t" data-i="{i}">{f["t"]:.0f}</th>' for i, f in enumerate(frames))
    marks = ""
    for i, f in enumerate(frames):
        lab = any(abs(f["t"] - l) <= 1.0 for l in args.label)
        ev = [ty for t, ty in events if abs(f["t"] - t) <= 0.6]
        marks += (f'<td class="m{" lab" if lab else ""}{" ev" if ev else ""}" data-i="{i}" '
                  f'title="{html.escape("; ".join(ev) + (" | метка разметки" if lab else ""))}"></td>')
    rows = ""
    for pid in probe_ids:
        cells = ""
        for i, f in enumerate(frames):
            a = f["a"].get(pid)
            cls = {"yes": "y", "no": "n", "unclear": "u"}.get(a, "x")
            cells += f'<td class="{cls}" data-i="{i}"></td>'
        rows += f'<tr><th class="p" title="{html.escape(questions[pid])}">{pid}</th>{cells}</tr>'

    data = json.dumps([{"t": f["t"], "a": f["a"], "r": f["r"], "full": f["full"], "zone": f["zone"]} for f in frames])
    ev_list = "".join(f"<li><b>{t:.1f} с</b> — {html.escape(ty)}</li>" for t, ty in events) or "<li>нарушений не найдено</li>"
    label_txt = ", ".join(f"{l:g} с" for l in args.label) or "без нарушения"
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Как видит модель</title>
<style>
:root {{ --bg:#fff; --fg:#1f2328; --muted:#656d76; --line:#d0d7de; --yes:#1a7f37; --no:#eaeef2; --un:#d4a72c; --ev:#cf222e; --lab:#8250df; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0d1117; --fg:#e6edf3; --muted:#8d96a0; --line:#30363d; --yes:#2ea043; --no:#21262d; --un:#bb8009; --ev:#f85149; --lab:#a371f7; }} }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:14px/1.45 system-ui,-apple-system,sans-serif; }}
main {{ max-width:1200px; margin:0 auto; padding:16px; }}
h1 {{ font-size:20px; margin:0 0 4px; }} .sub {{ color:var(--muted); margin:0 0 12px; }}
.grid {{ overflow-x:auto; border:1px solid var(--line); border-radius:8px; }}
table {{ border-collapse:collapse; }} td, th {{ padding:0; }}
th.p {{ position:sticky; left:0; background:var(--bg); text-align:right; padding:0 8px; font-weight:500; white-space:nowrap; cursor:help; }}
th.t {{ font-weight:400; color:var(--muted); font-size:11px; min-width:18px; cursor:pointer; }}
td {{ width:18px; height:18px; border:1px solid var(--bg); cursor:pointer; }}
td.y {{ background:var(--yes); }} td.n {{ background:var(--no); }} td.u {{ background:var(--un); }} td.x {{ background:transparent; }}
td.m {{ height:8px; }} td.m.ev {{ background:var(--ev); }} td.m.lab {{ box-shadow: inset 0 -3px 0 var(--lab); }}
.sel {{ outline:2px solid var(--fg); outline-offset:-2px; }}
.legend span {{ display:inline-block; width:12px; height:12px; border-radius:2px; vertical-align:-2px; margin:0 4px 0 12px; }}
.view {{ display:flex; gap:16px; flex-wrap:wrap; margin-top:16px; }}
.view figure {{ margin:0; }} .view img {{ max-height:520px; max-width:100%; border-radius:6px; border:1px solid var(--line); display:block; }}
figcaption {{ color:var(--muted); font-size:12px; margin-top:4px; }}
.ans {{ flex:1 1 260px; }} .ans div {{ padding:2px 0; border-bottom:1px solid var(--line); }}
.ans b.y {{ color:var(--yes); }} .ans b.n {{ color:var(--muted); }} .ans b.u {{ color:var(--un); }}
ul {{ margin:4px 0 12px; padding-left:20px; }}
</style></head><body><main>
<h1>Как видит модель: {html.escape(args.video.stem)}</h1>
<p class="sub">Разметка: {html.escape(label_txt)}. Кадров: {len(frames)}. Наведите на имя вопроса, чтобы увидеть его текст; кликните по кадру.</p>
<b>Найдено сервисом:</b><ul>{ev_list}</ul>
<div class="legend">
 <span style="background:var(--yes)"></span>да <span style="background:var(--no)"></span>нет
 <span style="background:var(--un)"></span>не уверена <span style="border:1px dashed var(--line)"></span>не спрашивали
 <span style="background:var(--ev)"></span>нарушение <span style="box-shadow:inset 0 -3px 0 var(--lab)"></span>метка разметки
</div>
<div class="grid"><table><tr><th class="p">с</th>{head}</tr><tr><th class="p"></th>{marks}</tr>{rows}</table></div>
<div class="view">
 <figure><img id="full" alt="кадр"><figcaption>Полный кадр: синяя рамка — рабочая зона, оранжевая — сейф</figcaption></figure>
 <figure><img id="zone" alt="кроп"><figcaption>Что получила модель (кроп рабочей зоны)</figcaption></figure>
 <div class="ans" id="ans"></div>
</div>
</main><script>
const F = {data};
const Q = {json.dumps(questions, ensure_ascii=False)};
function show(i) {{
  const f = F[i];
  document.getElementById("full").src = "data:image/jpeg;base64," + f.full;
  document.getElementById("zone").src = "data:image/jpeg;base64," + f.zone;
  const box = document.getElementById("ans"); box.textContent = "";
  const h = document.createElement("h3"); h.textContent = f.t.toFixed(1) + " с"; box.appendChild(h);
  for (const [k, v] of Object.entries(f.a)) {{
    const d = document.createElement("div");
    const b = document.createElement("b"); b.className = {{yes:"y", no:"n", unclear:"u"}}[v] || ""; b.textContent = v;
    d.append(k + ": ", b);
    if (f.r && f.r[k]) d.append(" — " + f.r[k]);
    d.title = Q[k] || ""; box.appendChild(d);
  }}
  document.querySelectorAll(".sel").forEach(e => e.classList.remove("sel"));
  document.querySelectorAll('[data-i="' + i + '"]').forEach(e => e.classList.add("sel"));
}}
document.querySelectorAll("[data-i]").forEach(e => e.addEventListener("click", () => show(+e.dataset.i)));
show(0);
</script></body></html>"""
    out = args.out or args.result.with_suffix(".html")
    out.write_text(page, encoding="utf-8")
    print(out, f"{out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
