"""Пайплайн анализа видео.

Этапы:
  1. нарезка кадров ffmpeg (FRAME_FPS, уменьшенные до FRAME_MAX_SIDE);
  2. проверка включённых правил из rules.json: на каждый кадр узкий вопрос к
     модели (vlm.ask); событие = серия из min_consecutive подряд ответов «yes»;
  3. кадры-доказательства вырезаются из ОРИГИНАЛА видео в полном разрешении;
  4. сборка JSON строго по схеме из ТЗ (раздел 10).

Сюда же потом подключаются детектор людей и логика зон: они выдают
кандидатные кадры, и только по ним вызывается модель (см. README).
"""
from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config, vlm

ProgressFn = Callable[[str, float], None]


class VideoError(RuntimeError):
    pass


@dataclass
class Frame:
    t: float
    path: Path


@dataclass
class Event:
    type: str
    t: float
    description: str
    evidence_times: list[float] = field(default_factory=list)
    rule: dict | None = None


# ---------------------------------------------------------------- ffmpeg ---

def probe_duration(video: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError as exc:
        raise VideoError("Не удалось прочитать видео (ffprobe не вернул длительность)") from exc


def extract_frames(video: Path, out_dir: Path, fps: float, max_side: int) -> list[Frame]:
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = f"scale='if(gt(iw,ih),{max_side},-2)':'if(gt(iw,ih),-2,{max_side})'"
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps={fps},{scale}",
         "-q:v", "3", str(out_dir / "f_%05d.jpg")],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise VideoError(f"ffmpeg не смог нарезать кадры: {proc.stderr.strip()[:200]}")
    paths = sorted(out_dir.glob("f_*.jpg"))
    return [Frame(t=i / fps, path=p) for i, p in enumerate(paths)]


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


# ----------------------------------------------------------------- rules ---

def load_rules(path: Path | None = None) -> list[dict]:
    path = path or config.RULES_PATH
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [r for r in data.get("rules", []) if r.get("enabled")]


def _rule_text(rule: dict) -> str:
    src = rule.get("source") or {}
    if src.get("verified") and src.get("document"):
        section = f", {src['section']}" if src.get("section") else ""
        return f"Правило: {src['document']}{section}."
    return "Норматив уточняется, результат требует проверки человеком."


def _describe(rule: dict, t: float, visible: str) -> str:
    parts = [f"{rule['observation']} (с {t:.1f} с)."]
    if visible:
        parts.append(f"На кадре: {visible.rstrip('.')}.")
    if rule.get("why"):
        parts.append(rule["why"])
    parts.append(_rule_text(rule))
    return " ".join(parts)


# ------------------------------------------------------------- detection ---

def _runs(hits: list[tuple[float, bool, str]], min_len: int, step: float) -> list[tuple[float, float, str]]:
    """Серии подряд идущих «yes»: (t_начала, t_конца, подпись_модели)."""
    runs, cur = [], []
    for t, ok, visible in hits:
        if ok:
            cur.append((t, visible))
        else:
            if len(cur) >= min_len:
                runs.append((cur[0][0], cur[-1][0], cur[0][1]))
            cur = []
    if len(cur) >= min_len:
        runs.append((cur[0][0], cur[-1][0], cur[0][1]))
    merged: list[tuple[float, float, str]] = []
    for r in runs:
        if merged and r[0] - merged[-1][1] <= config.MERGE_GAP_SEC:
            merged[-1] = (merged[-1][0], r[1], merged[-1][2])
        else:
            merged.append(r)
    return merged


def detect_by_rules(frames: list[Frame], rules: list[dict], deadline: float,
                    progress: ProgressFn) -> list[Event]:
    events: list[Event] = []
    calls_left = config.MAX_VLM_CALLS
    step = 1.0 / config.FRAME_FPS
    # если кадров больше бюджета вызовов, берём каждый n-й
    per_rule_budget = max(calls_left // max(len(rules), 1), 1)
    stride = max(1, -(-len(frames) // per_rule_budget))
    sampled = frames[::stride]
    total = max(len(rules) * len(sampled), 1)
    done = 0
    for rule in rules:
        hits: list[tuple[float, bool, str]] = []
        for fr in sampled:
            if time.monotonic() > deadline:
                break
            res = vlm.ask(fr.path, rule["question"])
            hits.append((fr.t, res["answer"] == "yes", res["what_is_visible"]))
            done += 1
            progress("Анализ кадров", 0.2 + 0.6 * done / total)
        for start, end, visible in _runs(hits, int(rule.get("min_consecutive", 2)), step * stride)[
                : config.MAX_EVENTS_PER_RULE]:
            times = sorted({round(start, 2), round((start + end) / 2, 2), round(end, 2)})
            events.append(Event(rule["type"], start, _describe(rule, start, visible), times, rule))
    return events


# ---------------------------------------------------------------- result ---

def build_result(job_id: str, video: Path, events: list[Event]) -> dict:
    violations = []
    for ev in sorted(events, key=lambda e: e.t):
        frames = []
        for t in ev.evidence_times[:3] or [ev.t]:
            jpeg = grab_frame_jpeg(video, t, config.EVIDENCE_MAX_SIDE)
            frames.append({"timestamp_sec": round(t, 1), "image_base64": base64.b64encode(jpeg).decode()})
        v = {
            "type": ev.type,
            "timecode_sec": round(ev.t, 1),
            "description": ev.description,
            "evidence_frames": frames,
        }
        src = (ev.rule or {}).get("source") or {}
        if src.get("verified") and src.get("document"):
            v["rule"] = {"document": src["document"], "section": src.get("section"), "url": src.get("url")}
        violations.append(v)
    return {
        "job_id": job_id,
        "status": "done",
        "verdict": "violation" if violations else "no_violation",
        "violations": violations,
    }


def analyze_video(job_id: str, video: Path, progress: ProgressFn | None = None) -> dict:
    progress = progress or (lambda stage, frac: None)
    deadline = time.monotonic() + config.TIME_BUDGET_SEC
    progress("Чтение видео", 0.02)
    duration = probe_duration(video)

    with tempfile.TemporaryDirectory(prefix="frames_") as tmp:
        progress("Нарезка кадров", 0.05)
        frames = extract_frames(video, Path(tmp), config.FRAME_FPS, config.FRAME_MAX_SIDE)
        if not frames:
            raise VideoError("В видео не найдено кадров")

        rules = load_rules()
        events: list[Event] = []
        if rules:
            events = detect_by_rules(frames, rules, deadline, progress)
        elif config.STUB_DEMO:
            t = round(duration / 2, 1)
            events = [Event(
                "ДЕМО: заглушка (модель не подключена)", t,
                "Это тестовое событие для проверки интерфейса. Реальный анализ не выполнялся.",
                [t],
            )]

        progress("Сборка результата", 0.9)
        return build_result(job_id, video, events)
