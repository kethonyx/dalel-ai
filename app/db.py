
"""Доступ к каталогу видео и сохранённым результатам анализа в PostgreSQL."""
from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import config


_WORKER_STATS_SQL = """SELECT w.id, w.name, w.created_at,
    COUNT(v.id)::int AS video_count,
    COUNT(r.id)::int AS analyzed_video_count,
    COALESCE(SUM(v.duration_sec) FILTER (WHERE r.id IS NOT NULL), 0)::float8 AS analyzed_duration_sec,
    COALESCE(SUM(e.violation_count), 0)::int AS violation_count
    FROM worker w
    LEFT JOIN videos v ON v.worker_id = w.id
    LEFT JOIN LATERAL (
        SELECT id FROM analysis_runs
        WHERE video_id = v.id AND status = 'done'
        ORDER BY created_at DESC, id DESC LIMIT 1
    ) r ON true
    LEFT JOIN LATERAL (
        SELECT COUNT(*)::int AS violation_count FROM events WHERE run_id = r.id
    ) e ON true
    GROUP BY w.id"""


@contextmanager
def connection():
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row, connect_timeout=5) as conn:
        yield conn


def check_connection() -> None:
    with connection() as conn:
        conn.execute("SELECT 1")


def add_worker(worker_id: UUID, name: str) -> dict:
    with connection() as conn:
        return conn.execute("""INSERT INTO worker (id, name) VALUES (%s, %s)
            RETURNING id, name, created_at""", (worker_id, name)).fetchone()


def get_worker(worker_id: UUID) -> dict | None:
    with connection() as conn:
        return conn.execute("SELECT id, name, created_at FROM worker WHERE id = %s",
                            (worker_id,)).fetchone()


def list_workers(limit: int = 100, offset: int = 0) -> list[dict]:
    with connection() as conn:
        return conn.execute(_WORKER_STATS_SQL +
                            " ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                            (limit, offset)).fetchall()


def get_worker_stats(worker_id: UUID) -> dict | None:
    with connection() as conn:
        return conn.execute("SELECT * FROM (" + _WORKER_STATS_SQL +
                            ") AS stats WHERE id = %s", (worker_id,)).fetchone()


def set_video_worker(video_id: UUID, worker_id: UUID | None) -> bool:
    with connection() as conn:
        return conn.execute("UPDATE videos SET worker_id = %s WHERE id = %s",
                            (worker_id, video_id)).rowcount == 1


def add_video(video_id: UUID, storage_key: str, original_name: str, media_type: str,
              size_bytes: int, duration_sec: float, worker_id: UUID | None = None) -> None:
    with connection() as conn:
        conn.execute("""INSERT INTO videos
            (id, worker_id, storage_key, original_name, media_type, size_bytes, duration_sec)
            VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (video_id, worker_id, storage_key, original_name, media_type, size_bytes, duration_sec))


def get_video(video_id: UUID) -> dict | None:
    with connection() as conn:
        return conn.execute("SELECT * FROM videos WHERE id = %s", (video_id,)).fetchone()


def list_videos(limit: int = 100, offset: int = 0, worker_id: UUID | None = None) -> list[dict]:
    where = "WHERE v.worker_id = %s" if worker_id is not None else ""
    params = (worker_id, limit, offset) if worker_id is not None else (limit, offset)
    with connection() as conn:
        return conn.execute("""SELECT v.*, r.id AS latest_run_id, r.status AS analysis_status,
            c.id AS latest_completed_run_id
            FROM videos v LEFT JOIN LATERAL (
                SELECT id, status FROM analysis_runs WHERE video_id = v.id
                ORDER BY created_at DESC, id DESC LIMIT 1
            ) r ON true
            LEFT JOIN LATERAL (
                SELECT id FROM analysis_runs WHERE video_id = v.id AND status = 'done'
                ORDER BY created_at DESC, id DESC LIMIT 1
            ) c ON true
            """ + where + " ORDER BY v.created_at DESC, v.id DESC LIMIT %s OFFSET %s",
            params).fetchall()


def add_run(run_id: UUID, video_id: UUID) -> None:
    with connection() as conn:
        conn.execute("""INSERT INTO analysis_runs (id, video_id, status)
                        VALUES (%s, %s, 'queued')""", (run_id, video_id))


def get_run(run_id: UUID) -> dict | None:
    with connection() as conn:
        return conn.execute("SELECT * FROM analysis_runs WHERE id = %s", (run_id,)).fetchone()


def latest_run(video_id: UUID, completed_only: bool = False) -> dict | None:
    condition = "AND status = 'done'" if completed_only else ""
    with connection() as conn:
        return conn.execute("SELECT * FROM analysis_runs WHERE video_id = %s " + condition +
                            " ORDER BY created_at DESC, id DESC LIMIT 1", (video_id,)).fetchone()


def requeue_unfinished() -> list[UUID]:
    # Один процесс приложения: при его перезапуске незавершённый анализ запускается вновь.
    with connection() as conn:
        conn.execute("""UPDATE analysis_runs SET status = 'queued', stage = 'В очереди',
                      progress = 0, updated_at = now() WHERE status = 'processing'""")
        return [row["id"] for row in conn.execute(
            "SELECT id FROM analysis_runs WHERE status = 'queued' ORDER BY created_at").fetchall()]


def claim_run(run_id: UUID) -> bool:
    with connection() as conn:
        return conn.execute("""UPDATE analysis_runs SET status = 'processing',
            stage = 'Чтение видео', updated_at = now()
            WHERE id = %s AND status = 'queued'""", (run_id,)).rowcount == 1


def set_progress(run_id: UUID, stage: str, progress: float) -> None:
    with connection() as conn:
        conn.execute("""UPDATE analysis_runs SET stage = %s, progress = %s,
            updated_at = now() WHERE id = %s""", (stage, round(progress, 2), run_id))


def finish_run(run_id: UUID, result: dict, frames: list[dict]) -> None:
    # Результат, кадры и события становятся видимыми вместе.
    with connection() as conn:
        with conn.cursor() as cur:
            for index, frame in enumerate(frames):
                cur.execute("""INSERT INTO frame_analyses
                    (run_id, frame_index, timestamp_sec, analysis_json)
                    VALUES (%s, %s, %s, %s)""",
                    (run_id, index, frame["t"], Jsonb({
                        "answers": frame.get("a", {}), "reasons": frame.get("r", {})})))
            for index, event in enumerate(result["violations"]):
                cur.execute("""INSERT INTO events
                    (run_id, event_index, timecode_sec, type, description, rule_json)
                    VALUES (%s, %s, %s, %s, %s, %s)""",
                    (run_id, index, event["timecode_sec"], event["type"],
                     event["description"], Jsonb(event.get("rule")) if event.get("rule") else None))
            cur.execute("""UPDATE analysis_runs SET status = 'done', stage = 'Готово',
                progress = 1, verdict = %s, result_json = %s, error = NULL,
                updated_at = now() WHERE id = %s""",
                (result["verdict"], Jsonb(result), run_id))


def fail_run(run_id: UUID, error: str) -> None:
    with connection() as conn:
        conn.execute("""UPDATE analysis_runs SET status = 'failed', stage = 'Ошибка',
            error = %s, updated_at = now() WHERE id = %s""", (error[:300], run_id))


def get_frames(run_id: UUID) -> list[dict]:
    with connection() as conn:
        return conn.execute("""SELECT frame_index, timestamp_sec, analysis_json AS analysis
            FROM frame_analyses WHERE run_id = %s ORDER BY frame_index""", (run_id,)).fetchall()


def get_events(run_id: UUID) -> list[dict]:
    with connection() as conn:
        return conn.execute("""SELECT event_index, timecode_sec, type, description, rule_json AS rule
            FROM events WHERE run_id = %s ORDER BY timecode_sec, event_index""", (run_id,)).fetchall()
