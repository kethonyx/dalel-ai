"""FastAPI-сервис: API для жюри (X-API-Key) + веб-интерфейс.

POST /api/v1/analyze        загрузить .mov (поле file) -> {"job_id": ...}
GET  /api/v1/jobs/{job_id}  статус (processing|done|failed) и результат
"""
from __future__ import annotations

import base64
import json
import logging
import queue
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, pipeline, rules as rule_engine

log = logging.getLogger("cashier")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

STATIC_DIR = Path(__file__).parent / "static"

_jobs: dict[str, dict] = {}
_live: dict[str, dict] = {}  # job_id -> ответы модели по кадрам во время обработки (в job.json не пишется)
_jobs_lock = threading.Lock()
_queue: "queue.Queue[str]" = queue.Queue()


# ---------------------------------------------------------------- хранение ---

def _job_dir(job_id: str) -> Path:
    return config.JOBS_DIR / job_id


def _save(job_id: str) -> None:
    with _jobs_lock:
        data = dict(_jobs[job_id])
    (_job_dir(job_id) / "job.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _update(job_id: str, **fields) -> None:
    with _jobs_lock:
        _jobs[job_id].update(fields)
    _save(job_id)


def _load_existing() -> None:
    config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    for f in config.JOBS_DIR.glob("*/job.json"):
        try:
            job = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if job.get("status") == "processing":  # сервис перезапускали посреди обработки
            job = {"job_id": job["job_id"], "status": "failed", "error": "Сервис был перезапущен во время обработки"}
        _jobs[job["job_id"]] = job


# ----------------------------------------------------------------- воркер ---

def _worker() -> None:
    """Один воркер: два видео не обрабатываются параллельно (экономим память GPU)."""
    while True:
        job_id = _queue.get()
        started = time.monotonic()
        try:
            video = next(_job_dir(job_id).glob("input.*"))

            def progress(stage: str, frac: float) -> None:
                with _jobs_lock:
                    _jobs[job_id]["stage"] = stage
                    _jobs[job_id]["progress"] = round(frac, 2)

            live = {"rows": [], "preview": None, "preview_t": None}
            with _jobs_lock:
                _live[job_id] = live

            def on_frame(row: dict, preview: bytes) -> None:
                with _jobs_lock:
                    live["rows"].append({"t": row["t"], "a": row["a"]})
                    live["preview"] = base64.b64encode(preview).decode()
                    live["preview_t"] = row["t"]

            result = pipeline.analyze_video(job_id, video, progress, on_frame=on_frame)
            fields = {k: v for k, v in result.items() if k != "job_id"}
            _update(job_id, **fields, stage="Готово", progress=1.0)
            log.info("job %s done in %.1fs, verdict=%s", job_id, time.monotonic() - started, result["verdict"])
        except Exception as exc:
            log.exception("job %s failed", job_id)
            _update(job_id, status="failed", error=str(exc)[:300])
        finally:
            with _jobs_lock:
                _live.pop(job_id, None)  # живой просмотр нужен только во время обработки
            _queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_existing()
    threading.Thread(target=_worker, daemon=True, name="worker").start()
    if config.API_KEY_GENERATED:
        log.warning("API_KEY не задан, сгенерирован временный: %s (задайте API_KEY в окружении)", config.API_KEY)
    log.info("VLM backend: %s", config.VLM_BACKEND)
    yield


app = FastAPI(title="Cashier discipline video analyzer", lifespan=lifespan)


# ---------------------------------------------------------------- вспомогательное ---

def require_key(x_api_key: str | None = Header(default=None)) -> None:
    ok = x_api_key is not None and secrets.compare_digest(
        x_api_key.encode("utf-8"), config.API_KEY.encode("utf-8"))
    if not ok:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


async def _create_job(file: UploadFile) -> dict:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in config.ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"Ожидается видео {', '.join(sorted(config.ALLOWED_EXT))}")
    job_id = uuid.uuid4().hex[:8]
    jdir = _job_dir(job_id)
    jdir.mkdir(parents=True, exist_ok=True)
    dest = jdir / f"input{ext}"
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"Файл больше {config.MAX_UPLOAD_MB} МБ")
            out.write(chunk)
    try:
        pipeline.probe_duration(dest)
    except pipeline.VideoError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with _jobs_lock:
        _jobs[job_id] = {"job_id": job_id, "status": "processing", "stage": "В очереди", "progress": 0.0}
    _save(job_id)
    _queue.put(job_id)
    return {"job_id": job_id, "status": "processing"}


def _job_view(job_id: str) -> dict:
    with _jobs_lock:
        job = _jobs.get(job_id)
        job = dict(job) if job else None
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] == "done":
        return {k: job[k] for k in ("job_id", "status", "verdict", "violations")}
    if job["status"] == "failed":
        return {"job_id": job_id, "status": "failed", "error": job.get("error", "unknown error")}
    return {"job_id": job_id, "status": "processing",
            "stage": job.get("stage"), "progress": job.get("progress", 0.0)}


# ---------------------------------------------------------------- API для жюри ---

@app.post("/api/v1/analyze", dependencies=[Depends(require_key)])
async def analyze(file: UploadFile = File(...)):
    return await _create_job(file)


@app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(require_key)])
def get_job(job_id: str):
    return _job_view(job_id)


@app.get("/health")
def health():
    return {"ok": True, "backend": config.VLM_BACKEND, "queue": _queue.qsize()}


# ---------------------------------------------------------------- веб-интерфейс ---

if config.UI_OPEN:
    @app.post("/ui/analyze")
    async def ui_analyze(file: UploadFile = File(...)):
        return await _create_job(file)

    @app.get("/ui/jobs/{job_id}")
    def ui_job(job_id: str):
        return _job_view(job_id)

    @app.get("/ui/jobs/{job_id}/live")
    def ui_job_live(job_id: str, since: int = 0):
        """Живой просмотр: что модель видит сейчас и что ответила по кадрам.

        since — сколько строк клиент уже получил; отдаём только новые.
        События пересчитываются по накопленным ответам (предварительно, без дозаполнения).
        """
        cfg = pipeline.load_rules()
        with _jobs_lock:
            live = _live.get(job_id)
            if live is None:
                return {"active": False}
            rows = sorted(live["rows"], key=lambda r: r["t"])
            preview, preview_t = live["preview"], live["preview_t"]
        events = rule_engine.evaluate(rows, cfg["rules"], config.MERGE_GAP_SEC, config.MAX_EVENTS_PER_RULE)
        return {
            "active": True,
            "probes": [{"id": p["id"], "title": p.get("title", p["id"])} for p in cfg["probes"]],
            "total": len(rows),
            "rows": rows[since:] if since <= len(rows) else rows,
            "preview": preview,
            "preview_t": preview_t,
            "events": [{"t": round(e.t, 1), "type": e.rule["type"]} for e in events],
        }


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
