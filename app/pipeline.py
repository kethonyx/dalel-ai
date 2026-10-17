"""Пайплайн анализа видео.

Этапы:
  1. нарезка кадров ffmpeg: до FRAME_FPS кадров/с, не больше MAX_FRAMES на видео;
  2. рабочая зона: модель один раз находит стол, сейф и счётную машинку (grounding)
     на нескольких кадрах — кропы не зависят от ракурса камеры;
  3. по каждому кадру модель отвечает на короткие вопросы yes/no (probes из rules.json)
     на нужном кропе; вопросы с полем `when` задаются только при выполнении условия;
  4. правила (app/rules.py) ищут события на временной шкале ответов;
  5. кадры-доказательства вырезаются из ОРИГИНАЛА видео в момент события;
  6. сборка JSON строго по схеме из ТЗ (раздел 10).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from PIL import Image

from . import config, rules as rule_engine, vlm

ProgressFn = Callable[[str, float], None]


class VideoError(RuntimeError):
    pass


# ---------------------------------------------------------------- ffmpeg ---

def probe_duration(video: Path) -> float:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(video)],
            capture_output=True, text=True, timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise VideoError("ffprobe недоступен или не ответил вовремя") from exc
    try:
        info = json.loads(proc.stdout)
        duration = float(info["format"]["duration"])
        if proc.returncode or not info.get("streams") or not math.isfinite(duration) or duration <= 0:
            raise ValueError
        return duration
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise VideoError("Не удалось прочитать видео или в нём нет видеодорожки") from exc


def sample_step(duration: float) -> float:
    """Шаг между кадрами: 1/FRAME_FPS, но длинные видео прореживаются до MAX_FRAMES."""
    n = max(1, min(config.MAX_FRAMES, math.ceil(duration * config.FRAME_FPS)))
    return duration / n


def extract_frames(video: Path, out_dir: Path, step: float) -> list[dict]:
    """Кадр k приходится на момент k*step; длинная сторона до 1280 (из них режутся кропы)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = "scale='if(gt(iw,ih),min(1280,iw),-2)':'if(gt(iw,ih),-2,min(1280,ih))'"
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps={1 / step:.6f},{scale}",
         "-q:v", "2", str(out_dir / "f_%05d.jpg")],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise VideoError(f"ffmpeg не смог нарезать кадры: {proc.stderr.strip()[:200]}")
    paths = sorted(out_dir.glob("f_*.jpg"))
    return [{"t": round(k * step, 2), "path": p} for k, p in enumerate(paths)]


def grab_frame_jpeg(video: Path, t: float, max_side: int) -> bytes:
    """Точный кадр из оригинала по времени t (полное разрешение, до max_side)."""
    scale = f"scale='if(gt(iw,ih),min({max_side},iw),-2)':'if(gt(iw,ih),-2,min({max_side},ih))'"
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", str(video),
         "-frames:v", "1", "-vf", scale, "-q:v", "3", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise VideoError(f"Не удалось вырезать кадр на {t:.2f} с")
    return proc.stdout


def extract_poster(video: Path, output: Path, duration: float) -> None:
    """Save a browser-independent JPEG preview frame beside a stored video."""
    output.parent.mkdir(parents=True, exist_ok=True)
    timestamp = min(5.0, max(0.05, duration * 0.12))
    scale = "scale='if(gt(iw,ih),min(640,iw),-2)':'if(gt(iw,ih),-2,min(640,ih))'"
    try:
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{timestamp:.3f}", "-i", str(video),
             "-frames:v", "1", "-vf", scale, "-q:v", "3", "-y", str(output)],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise VideoError("Не удалось создать превью видео") from exc
    if proc.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        raise VideoError(f"Не удалось создать превью видео: {proc.stderr.strip()[:200]}")


# ----------------------------------------------------------------- images ---

def to_jpeg(img: Image.Image, max_side: int, min_side: int = 0) -> bytes:
    s = max_side / max(img.size)
    if min_side and min(img.size) * s < min_side:
        s = min_side / min(img.size)
    if abs(s - 1) > 0.01:
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def crop_frac(img: Image.Image, box: tuple[float, float, float, float]) -> Image.Image:
    W, H = img.size
    return img.crop((int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)))


def union(boxes: list[tuple]) -> tuple | None:
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def pad(box: tuple, px: float, top: float, bottom: float) -> tuple:
    w, h = box[2] - box[0], box[3] - box[1]
    return (max(0.0, box[0] - w * px), max(0.0, box[1] - h * top),
            min(1.0, box[2] + w * px), min(1.0, box[3] + h * bottom))


def find_zones(frames: list[dict], zone_cfg: dict) -> dict:
    """Рабочая зона и сейф по 3 кадрам (начало, середина, конец): объединение рамок.

    Если модель ничего не нашла, зона = весь кадр, а вопросы по сейфу пропускаются.
    """
    picks = [frames[0], frames[len(frames) // 2], frames[-1]] if len(frames) >= 3 else frames
    found: dict[str, list] = {}
    for fr in picks:
        img = Image.open(fr["path"]).convert("RGB")
        for item in vlm.ground(to_jpeg(img, config.FRAME_MAX_SIDE), zone_cfg["labels"], img.width, img.height):
            found.setdefault(item["label"].lower(), []).append(item["box"])
    zone = union([b for boxes in found.values() for b in boxes])
    safe = union(found.get("metal safe", []))
    desk = union(found.get("cashier desk", []))
    zone_box = pad(zone, zone_cfg.get("pad_x", 0.15), zone_cfg.get("pad_top", 0.5),
                   zone_cfg.get("pad_bottom", 0.2)) if zone else (0.0, 0.0, 1.0, 1.0)
    return {
        "zone": zone_box,
        "safe": pad(safe, 0.6, 0.4, 0.4) if safe else None,
        # поверхность стола и руки над ней: предметы в руках крупнее, чем на кропе всей зоны
        # (купюры vs удостоверение: 16/19 против 15/19 на тестовых кадрах, Qwen3-VL-8B)
        "desk": pad(desk, 0.05, 0.6, 0.0) if desk else zone_box,
        "found": {k: len(v) for k, v in found.items()},
    }


# ------------------------------------------------------------------ probes ---

class AnswerCache:
    def __init__(self, root: Path, model: str):
        self.root = root
        self.model = model.encode()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, jpeg: bytes, question: str) -> Path:
        h = hashlib.sha1(jpeg + b"\0" + question.encode() + b"\0" + self.model).hexdigest()
        return self.root / h[:2] / f"{h}.json"

    def get(self, jpeg: bytes, question: str) -> dict | None:
        p = self._path(jpeg, question)
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return None

    def put(self, jpeg: bytes, question: str, res: dict) -> None:
        p = self._path(jpeg, question)
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(res, ensure_ascii=False))


def probe_frame(fr: dict, idx: int, probes: list[dict], zones: dict, cache: AnswerCache | None) -> dict:
    img = Image.open(fr["path"]).convert("RGB")
    crops: dict[str, bytes | None] = {}

    def crop(kind: str) -> bytes | None:
        if kind not in crops:
            if kind == "full":
                crops[kind] = to_jpeg(img, config.FULL_MAX_SIDE)
            elif kind == "zone":
                crops[kind] = to_jpeg(crop_frac(img, zones["zone"]), config.FRAME_MAX_SIDE)
            elif kind == "desk":
                crops[kind] = to_jpeg(crop_frac(img, zones.get("desk") or zones["zone"]), config.FRAME_MAX_SIDE)
            elif kind == "safe":
                crops[kind] = (to_jpeg(crop_frac(img, zones["safe"]), config.FRAME_MAX_SIDE, min_side=448)
                               if zones.get("safe") else None)
            else:
                raise ValueError(f"Неизвестный кроп {kind!r}")
        return crops[kind]

    answers, reasons = {}, {}
    for pr in probes:  # порядок важен: условия `when` ссылаются на уже заданные вопросы
        if idx % int(pr.get("every", 1)):
            continue
        if not rule_engine.matches(answers, pr.get("when", {})):
            continue
        jpeg = crop(pr.get("crop", "zone"))
        if jpeg is None:
            continue
        options = pr.get("options")  # вопрос с выбором варианта: {ключ: текст}
        key = vlm.choice_prompt(pr["question"], options) if options else pr["question"]
        res = cache.get(jpeg, key) if cache else None
        if res is None:
            res = vlm.ask_choice(jpeg, pr["question"], options) if options else vlm.ask(jpeg, pr["question"])
            if cache and res["answer"] != "unclear":
                cache.put(jpeg, key, res)
        answers[pr["id"]] = res["answer"]
        reasons[pr["id"]] = res["reason"]
    preview = to_jpeg(crop_frac(img, zones["zone"]), 360)  # для живого просмотра в интерфейсе
    return {"t": fr["t"], "a": answers, "r": reasons}, preview


def fill_sparse(timeline: list[dict], probes: list[dict]) -> None:
    """Вопросы с every > 1 задаются не на каждом кадре: переносим последний ответ вперёд."""
    for pr in probes:
        every = int(pr.get("every", 1))
        if every <= 1:
            continue
        last, age = None, 0
        for fr in timeline:
            if pr["id"] in fr["a"]:
                last, age = fr["a"][pr["id"]], 0
            elif last is not None and age < every - 1 and rule_engine.matches(fr["a"], pr.get("when", {})):
                fr["a"][pr["id"]] = last
                age += 1


# ----------------------------------------------------------------- rules ---

def load_rules(path: Path | None = None) -> dict:
    data = json.loads(Path(path or config.RULES_PATH).read_text(encoding="utf-8"))
    data["rules"] = [r for r in data.get("rules", []) if r.get("enabled")]
    return data


def _rule_text(rule: dict) -> str:
    src = rule.get("source") or {}
    if src.get("verified") and src.get("document"):
        section = f", {src['section']}" if src.get("section") else ""
        return f"Правило: {src['document']}{section}."
    return "Норматив уточняется, результат требует проверки человеком."


def describe(rule: dict, t: float) -> str:
    parts = [f"{rule['observation']} (с {t:.1f} с)."]
    if rule.get("why"):
        parts.append(rule["why"])
    parts.append(_rule_text(rule))
    return " ".join(parts)


# ---------------------------------------------------------------- result ---

def build_result(job_id: str, video: Path, events: list[rule_engine.Event]) -> dict:
    violations = []
    for ev in sorted(events, key=lambda e: e.t):
        frames = []
        for t in ev.evidence_times[:3] or [ev.t]:
            jpeg = grab_frame_jpeg(video, t, config.EVIDENCE_MAX_SIDE)
            frames.append({"timestamp_sec": round(t, 1), "image_base64": base64.b64encode(jpeg).decode()})
        v = {
            "type": ev.rule["type"],
            "timecode_sec": round(ev.t, 1),
            "description": describe(ev.rule, ev.t),
            "evidence_frames": frames,
        }
        src = ev.rule.get("source") or {}
        if src.get("verified") and src.get("document"):
            v["rule"] = {"document": src["document"], "section": src.get("section"), "url": src.get("url")}
        violations.append(v)
    return {
        "job_id": job_id,
        "status": "done",
        "verdict": "violation" if violations else "no_violation",
        "violations": violations,
    }


FrameFn = Callable[[dict, bytes], None]


def analyze_video(job_id: str, video: Path, progress: ProgressFn | None = None,
                  rules_path: Path | None = None, on_frame: FrameFn | None = None) -> dict:
    """on_frame(row, preview_jpeg) вызывается после каждого кадра — для живого просмотра."""
    progress = progress or (lambda stage, frac: None)
    deadline = time.monotonic() + config.TIME_BUDGET_SEC
    progress("Чтение видео", 0.02)
    duration = probe_duration(video)
    cfg = load_rules(rules_path)
    cache = AnswerCache(config.CACHE_DIR, vlm.model_id())

    with tempfile.TemporaryDirectory(prefix="frames_") as tmp:
        progress("Нарезка кадров", 0.05)
        frames = extract_frames(video, Path(tmp), sample_step(duration))
        if not frames:
            raise VideoError("В видео не найдено кадров")

        timeline: list[dict] = []
        zones: dict = {}
        if cfg["rules"] and config.VLM_BACKEND != "stub":
            progress("Поиск рабочей зоны", 0.08)
            zones = find_zones(frames, cfg.get("zone", {"labels": []}))
            done, lock = [0], threading.Lock()

            def work(i_fr):
                i, fr = i_fr
                if time.monotonic() > deadline:
                    return None  # бюджет времени исчерпан: отдаём то, что успели
                row, preview = probe_frame(fr, i, cfg["probes"], zones, cache)
                with lock:
                    done[0] += 1
                    progress("Анализ кадров", 0.1 + 0.75 * done[0] / len(frames))
                if on_frame:
                    on_frame(row, preview)
                return row

            with ThreadPoolExecutor(max(1, config.VLM_PARALLEL)) as ex:
                timeline = [r for r in ex.map(work, enumerate(frames)) if r is not None]
            fill_sparse(timeline, cfg["probes"])

        events = rule_engine.evaluate(timeline, cfg["rules"], config.MERGE_GAP_SEC, config.MAX_EVENTS_PER_RULE)
        if config.VLM_BACKEND == "stub" and config.STUB_DEMO:
            t = round(duration / 2, 1)
            demo = {"type": "ДЕМО: заглушка (модель не подключена)",
                    "observation": "Это тестовое событие для проверки интерфейса. Реальный анализ не выполнялся"}
            events = [rule_engine.Event(demo, t, [t])]

        progress("Сборка результата", 0.9)
        result = build_result(job_id, video, events)
        # служебное, в API не отдаётся (main._job_view фильтрует поля): для отладки и подбора правил
        result["_debug"] = {"duration": duration, "frames_total": len(frames), "frames_analyzed": len(timeline),
                            "zones": zones, "timeline": timeline}
        return result
