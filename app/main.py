"""Загрузка видео, сохранённый анализ и API для жюри и плеера."""
from __future__ import annotations

import json
import logging
import os
import queue
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import anyio
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import config, pipeline

log = logging.getLogger("cashier")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
STATIC_DIR = Path(__file__).parent / "static"

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_queue: "queue.Queue[str]" = queue.Queue()


def _video_file(video: dict) -> Path:
    # storage_key генерируется сервером при загрузке, а не берётся из URL пользователя.
    return config.DATA_DIR / video["storage_key"]


def _worker() -> None:
    """Один анализ за раз; очередь восстанавливается из PostgreSQL после перезапуска."""
    while True:
        run_id = _queue.get()
        started = time.monotonic()
        try:
            if not db.claim_run(run_id):
                continue
            run = db.get_run(run_id)
            video = db.get_video(run["video_id"])
            if video is None or not _video_file(video).is_file():
                raise FileNotFoundError("Исходный видеофайл не найден")

            def progress(stage: str, frac: float) -> None:
                db.set_progress(run_id, stage, frac)

            result = pipeline.analyze_video(job_id, video, progress)
            fields = {k: v for k, v in result.items() if k != "job_id"}
            _update(job_id, **fields, stage="Готово", progress=1.0)
            log.info("job %s done in %.1fs, verdict=%s", job_id, time.monotonic() - started, result["verdict"])
        except Exception as exc:
            log.exception("job %s failed", run_id)
            try:
                db.fail_run(run_id, str(exc))
            except Exception:
                log.exception("could not record failure for job %s", run_id)
        finally:
            with _jobs_lock:
                _live.pop(job_id, None)  # живой просмотр нужен только во время обработки
            _queue.task_done()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.check_connection()
    for run_id in db.requeue_unfinished():
        _queue.put(run_id)
    threading.Thread(target=_worker, daemon=True, name="video-worker").start()
    if config.API_KEY_GENERATED:
        log.warning("API_KEY не задан, сгенерирован временный: %s", config.API_KEY)
    log.info("VLM backend: %s", config.VLM_BACKEND)
    yield


app = FastAPI(title="Cashier discipline video analyzer", lifespan=lifespan)


def _valid_key(key: str | None) -> bool:
    return key is not None and secrets.compare_digest(key.encode(), config.API_KEY.encode())


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    if not _valid_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def _signed_stream_url(video_id: UUID) -> str:
    expires = int(time.time()) + 3600
    payload = f"{video_id}:{expires}".encode()
    signature = hmac.new(config.API_KEY.encode(), payload, hashlib.sha256).hexdigest()
    return f"/api/v1/videos/{video_id}/stream?expires={expires}&signature={signature}"


def _stream_authorized(request: Request, video_id: UUID,
                       expires: int | None, signature: str | None) -> bool:
    if _valid_key(request.headers.get("X-API-Key")):
        return True
    if expires is None or signature is None or expires < time.time():
        return False
    expected = hmac.new(config.API_KEY.encode(), f"{video_id}:{expires}".encode(),
                        hashlib.sha256).hexdigest()
    return secrets.compare_digest(signature, expected)


async def _store_video(file: UploadFile) -> dict:
    original_name = Path(file.filename or "").name
    ext = Path(original_name).suffix.lower()
    if ext not in config.ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"Ожидается видео {', '.join(sorted(config.ALLOWED_EXT))}")

    video_id = uuid4()
    folder = config.VIDEOS_DIR / str(video_id)
    folder.mkdir(parents=True, exist_ok=False)
    temp = folder / "upload.part"
    dest = folder / f"source{ext}"
    size = 0
    try:
        async with await anyio.open_file(temp, "wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > config.MAX_UPLOAD_MB * 1024 * 1024:
                    raise HTTPException(status_code=413, detail=f"Файл больше {config.MAX_UPLOAD_MB} МБ")
                await out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Пустой файл")
        try:
            duration = await run_in_threadpool(pipeline.probe_duration, temp)
        except pipeline.VideoError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        os.replace(temp, dest)
        media_type = "video/mp4" if ext in {".mp4", ".m4v"} else "video/quicktime"
        storage_key = str(dest.relative_to(config.DATA_DIR))
        await run_in_threadpool(db.add_video, video_id, storage_key, original_name,
                                media_type, size, duration)
        return {"id": video_id, "storage_key": storage_key, "original_name": original_name,
                "media_type": media_type, "size_bytes": size, "duration_sec": duration}
    except Exception:
        temp.unlink(missing_ok=True)
        dest.unlink(missing_ok=True)
        folder.rmdir()
        raise


def _start_run(video_id: UUID, force: bool = False) -> dict:
    video = db.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    latest = db.latest_run(video_id)
    if latest and (latest["status"] in {"queued", "processing"} or
                   latest["status"] == "done" and not force):
        return {"video_id": str(video_id), "job_id": str(latest["id"]),
                "status": "processing" if latest["status"] in {"queued", "processing"} else "done"}
    run_id = uuid4()
    db.add_run(run_id, video_id)
    _queue.put(run_id)
    return {"video_id": str(video_id), "job_id": str(run_id), "status": "processing"}


def _job_view(job_id: UUID, include_video: bool = False) -> dict:
    run = db.get_run(job_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if run["status"] == "done":
        view = run["result_json"]
    elif run["status"] == "failed":
        view = {"job_id": str(job_id), "status": "failed", "error": run["error"] or "unknown error"}
    else:
        view = {"job_id": str(job_id), "status": "processing",
                "stage": run["stage"], "progress": run["progress"]}
    if include_video:
        view = {**view, "video_id": str(run["video_id"]),
                "stream_url": _signed_stream_url(run["video_id"])}
    return view


def _video_view(video: dict) -> dict:
    latest = db.latest_run(video["id"]) if "latest_run_id" not in video else None
    completed = db.latest_run(video["id"], completed_only=True) if "latest_completed_run_id" not in video else None
    run_id = latest["id"] if latest else video.get("latest_run_id")
    status = latest["status"] if latest else video.get("analysis_status")
    return {"video_id": str(video["id"]), "original_name": video["original_name"],
            "size_bytes": video["size_bytes"], "duration_sec": video["duration_sec"],
            "created_at": video["created_at"].isoformat(),
            "job_id": str(run_id) if run_id else None,
            "latest_completed_job_id": str(completed["id"] if completed else video.get("latest_completed_run_id"))
            if completed or video.get("latest_completed_run_id") else None,
            "analysis_status": status,
            "stream_url": _signed_stream_url(video["id"])}


def _selected_run(video_id: UUID, run_id: UUID | None) -> dict | None:
    if db.get_video(video_id) is None:
        raise HTTPException(status_code=404, detail="Video not found")
    run = db.get_run(run_id) if run_id else db.latest_run(video_id, completed_only=True)
    if run is not None and run["video_id"] != video_id:
        raise HTTPException(status_code=404, detail="Job not found for video")
    return run


# API жюри: контракт ТЗ сохранён.
@app.post("/api/v1/analyze", dependencies=[Depends(require_key)])
async def analyze(file: UploadFile = File(...)):
    video = await _store_video(file)
    run = _start_run(video["id"])
    return {"job_id": run["job_id"], "status": run["status"]}


@app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(require_key)])
def get_job(job_id: UUID):
    return _job_view(job_id)


# API сохранённых видео и временной шкалы.
@app.post("/api/v1/videos", dependencies=[Depends(require_key)], status_code=202)
async def upload_video(file: UploadFile = File(...)):
    video = await _store_video(file)
    return _start_run(video["id"])


@app.get("/api/v1/videos", dependencies=[Depends(require_key)])
def list_videos(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0)):
    return {"items": [_video_view(video) for video in db.list_videos(limit, offset)]}


@app.get("/api/v1/videos/{video_id}", dependencies=[Depends(require_key)])
def get_video(video_id: UUID):
    video = db.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return _video_view(video)


@app.post("/api/v1/videos/{video_id}/analyze", dependencies=[Depends(require_key)], status_code=202)
def analyze_saved_video(video_id: UUID, force: bool = False):
    return _start_run(video_id, force)


@app.get("/api/v1/videos/{video_id}/events", dependencies=[Depends(require_key)])
def get_video_events(video_id: UUID, run_id: UUID | None = None):
    run = _selected_run(video_id, run_id)
    events = db.get_events(run["id"]) if run and run["status"] == "done" else []
    if events:
        violations = run["result_json"]["violations"]
        for event in events:
            event["evidence_frames"] = violations[event["event_index"]]["evidence_frames"]
    return {"video_id": str(video_id), "job_id": str(run["id"]) if run else None,
            "events": events}


@app.get("/api/v1/videos/{video_id}/frames", dependencies=[Depends(require_key)])
def get_video_frames(video_id: UUID, run_id: UUID | None = None):
    run = _selected_run(video_id, run_id)
    return {"video_id": str(video_id), "job_id": str(run["id"]) if run else None,
            "frames": db.get_frames(run["id"]) if run and run["status"] == "done" else []}


@app.get("/api/v1/videos/{video_id}/stream")
def stream_video(video_id: UUID, request: Request,
                 expires: int | None = None, signature: str | None = None):
    if not _stream_authorized(request, video_id, expires, signature):
        raise HTTPException(status_code=401, detail="Invalid video access token")
    video = db.get_video(video_id)
    if video is None or not _video_file(video).is_file():
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(_video_file(video), media_type=video["media_type"],
                        filename=video["original_name"], content_disposition_type="inline")


@app.get("/health")
def health():
    db.check_connection()
    return {"ok": True, "backend": config.VLM_BACKEND, "queue": _queue.qsize()}


if config.UI_OPEN:
    @app.post("/ui/analyze")
    async def ui_analyze(file: UploadFile = File(...)):
        video = await _store_video(file)
        return _start_run(video["id"])

    @app.get("/ui/jobs/{job_id}")
    def ui_job(job_id: UUID):
        return _job_view(job_id, include_video=True)

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
