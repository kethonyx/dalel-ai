"""Интеграция API с PostgreSQL; запускать с TEST_DATABASE_URL."""
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app import config, db
from app.main import app


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "нужен TEST_DATABASE_URL")
class SavedVideoAPI(unittest.TestCase):
    def test_upload_result_reopen_and_seek(self):
        frame_ready = threading.Event()
        continue_analyze = threading.Event()

        def fake_analyze(job_id, path, progress, on_frame=None):
            progress("Анализ кадров", 0.5)
            on_frame({"t": 1.25, "a": {"probe": "yes"}}, b"preview")
            on_frame({"t": 0.5, "a": {"probe": "no"}}, b"preview")
            frame_ready.set()
            continue_analyze.wait(2)
            return {
                "job_id": job_id, "status": "done", "verdict": "violation",
                "violations": [{"type": "Тестовое событие", "timecode_sec": 1.25,
                                "description": "На кадре видно тестовое действие.",
                                "evidence_frames": [{"timestamp_sec": 1.25, "image_base64": "dGVzdA=="}]}],
                "_debug": {"timeline": [{"t": 1.25, "a": {"probe": "yes"},
                                          "r": {"probe": "видно действие"}}]},
            }

        video_id = None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(config, "DATA_DIR", root), patch.object(config, "VIDEOS_DIR", root / "videos"), \
                 patch.object(config, "DATABASE_URL", os.environ["TEST_DATABASE_URL"]), \
                 patch("app.main.pipeline.probe_duration", return_value=2.0), \
                 patch("app.main.pipeline.analyze_video", side_effect=fake_analyze) as analyzer, \
                 patch("app.main.db.requeue_unfinished", return_value=[]):
                try:
                    with TestClient(app) as client:
                        headers = {"X-API-Key": config.API_KEY}
                        self.assertEqual(client.get("/api/v1/videos").status_code, 401)
                        uploaded = client.post("/api/v1/videos", headers=headers,
                                               files={"file": ("clip.mov", b"video-bytes", "video/quicktime")})
                        self.assertEqual(uploaded.status_code, 202, uploaded.text)
                        video_id = uploaded.json()["video_id"]
                        job_id = uploaded.json()["job_id"]
                        self.assertTrue(frame_ready.wait(2), "анализ не начался")
                        live = client.get(f"/ui/jobs/{job_id}/live").json()
                        self.assertTrue(live["active"])
                        self.assertEqual(live["rows"], [
                            {"t": 1.25, "a": {"probe": "yes"}},
                            {"t": 0.5, "a": {"probe": "no"}},
                        ])
                        later = client.get(f"/ui/jobs/{job_id}/live?since=1").json()
                        self.assertEqual(later["rows"], [{"t": 0.5, "a": {"probe": "no"}}])
                        self.assertEqual(live["preview"], "cHJldmlldw==")
                        continue_analyze.set()
                        for _ in range(100):
                            result = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
                            if result["status"] == "done":
                                break
                            time.sleep(0.02)
                        self.assertEqual(result["status"], "done", result)
                        self.assertEqual(result["violations"][0]["timecode_sec"], 1.25)

                        events = client.get(f"/api/v1/videos/{video_id}/events", headers=headers).json()["events"]
                        self.assertEqual(events[0]["description"], "На кадре видно тестовое действие.")
                        frames = client.get(f"/api/v1/videos/{video_id}/frames", headers=headers).json()["frames"]
                        self.assertEqual(frames[0]["analysis"]["answers"]["probe"], "yes")
                        metadata = client.get(f"/api/v1/videos/{video_id}", headers=headers).json()
                        self.assertEqual(metadata["job_id"], job_id)
                        self.assertIsNone(metadata["worker_id"])
                        listed = client.get("/api/v1/videos", headers=headers).json()["items"]
                        self.assertIn(video_id, [item["video_id"] for item in listed])

                        video = client.get(metadata["stream_url"], headers={"Range": "bytes=0-4"})
                        self.assertEqual(video.status_code, 206)
                        self.assertEqual(video.content, b"video")
                        self.assertEqual(video.headers["content-range"], "bytes 0-4/11")
                        reopened = client.post(f"/api/v1/videos/{video_id}/analyze", headers=headers).json()
                        self.assertEqual(reopened["job_id"], job_id)
                        analyzer.assert_called_once()
                finally:
                    continue_analyze.set()
                    if video_id is not None:
                        with db.connection() as conn:
                            conn.execute("DELETE FROM videos WHERE id = %s", (UUID(video_id),))

    def test_worker_video_upload_and_listing(self):
        def fake_analyze(job_id, path, progress, on_frame=None):
            return {"job_id": job_id, "status": "done", "verdict": "no_violation",
                    "violations": [], "_debug": {"timeline": []}}

        worker_ids = []
        video_id = None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(config, "DATA_DIR", root), patch.object(config, "VIDEOS_DIR", root / "videos"), \
                 patch.object(config, "DATABASE_URL", os.environ["TEST_DATABASE_URL"]), \
                 patch("app.main.pipeline.probe_duration", return_value=2.0), \
                 patch("app.main.pipeline.analyze_video", side_effect=fake_analyze), \
                 patch("app.main.db.requeue_unfinished", return_value=[]):
                try:
                    with TestClient(app) as client:
                        headers = {"X-API-Key": config.API_KEY}
                        self.assertEqual(client.post("/api/v1/new-worker", json={"name": "Кассир"}).status_code, 401)
                        self.assertEqual(client.post("/api/v1/new-worker", headers=headers,
                                                     json={"name": "   "}).status_code, 422)
                        for name in ("Кассир А", "Кассир Б"):
                            response = client.post("/api/v1/new-worker", headers=headers,
                                                   json={"name": f"  {name}  "})
                            self.assertEqual(response.status_code, 201, response.text)
                            self.assertEqual(response.json()["name"], name)
                            worker_ids.append(UUID(response.json()["worker_id"]))

                        self.assertEqual(client.get("/api/v1/workers").status_code, 401)
                        workers = client.get("/api/v1/workers", headers=headers).json()["items"]
                        created = [item for item in workers if UUID(item["worker_id"]) in worker_ids]
                        self.assertEqual({item["name"] for item in created}, {"Кассир А", "Кассир Б"})
                        self.assertTrue(all(item["created_at"] for item in created))

                        missing = uuid4()
                        self.assertEqual(client.get(f"/api/v1/workers/{missing}/videos",
                                                    headers=headers).status_code, 404)
                        self.assertEqual(client.post(f"/api/v1/workers/{missing}/videos", headers=headers,
                                                     files={"file": ("clip.mov", b"video", "video/quicktime")}).status_code, 404)
                        self.assertFalse((root / "videos").exists())

                        uploaded = client.post(f"/api/v1/workers/{worker_ids[0]}/videos", headers=headers,
                                               files={"file": ("clip.mov", b"video", "video/quicktime")})
                        self.assertEqual(uploaded.status_code, 202, uploaded.text)
                        self.assertEqual(uploaded.json()["worker_id"], str(worker_ids[0]))
                        video_id = UUID(uploaded.json()["video_id"])
                        for _ in range(100):
                            result = client.get(f"/api/v1/jobs/{uploaded.json()['job_id']}", headers=headers).json()
                            if result["status"] == "done":
                                break
                            time.sleep(0.02)
                        self.assertEqual(result["status"], "done", result)
                        self.assertEqual(db.get_video(video_id)["worker_id"], worker_ids[0])
                        listing = client.get(f"/api/v1/workers/{worker_ids[0]}/videos", headers=headers).json()
                        self.assertEqual(listing["worker_id"], str(worker_ids[0]))
                        self.assertEqual([item["video_id"] for item in listing["items"]], [str(video_id)])
                        self.assertEqual(listing["items"][0]["worker_id"], str(worker_ids[0]))
                        other = client.get(f"/api/v1/workers/{worker_ids[1]}/videos", headers=headers).json()
                        self.assertEqual(other["items"], [])
                finally:
                    with db.connection() as conn:
                        if video_id is not None:
                            conn.execute("DELETE FROM videos WHERE id = %s", (video_id,))
                        for worker_id in worker_ids:
                            conn.execute("DELETE FROM worker WHERE id = %s", (worker_id,))

    def test_worker_rating_uses_latest_completed_analysis(self):
        worker_ids = [uuid4(), uuid4()]
        video_ids = [uuid4() for _ in range(3)]
        with patch.object(config, "DATABASE_URL", os.environ["TEST_DATABASE_URL"]), \
             patch("app.main.db.requeue_unfinished", return_value=[]):
            try:
                db.add_worker(worker_ids[0], "Рейтинг А")
                db.add_worker(worker_ids[1], "Рейтинг Б")
                for index, video_id in enumerate(video_ids):
                    db.add_video(video_id, f"rating-test/{video_id}.mov", f"clip-{index}.mov",
                                 "video/quicktime", 10, 2.0, worker_ids[0])

                def finish(video_id, violations):
                    run_id = uuid4()
                    db.add_run(run_id, video_id)
                    db.finish_run(run_id, {"job_id": str(run_id), "status": "done",
                                           "verdict": "violation" if violations else "no_violation",
                                           "violations": [{"type": "Событие", "timecode_sec": float(i),
                                                           "description": "Признак нарушения"}
                                                          for i in range(violations)]}, [])
                    return run_id

                old_run = finish(video_ids[0], 2)
                with db.connection() as conn:
                    conn.execute("UPDATE analysis_runs SET created_at = now() - interval '1 day' WHERE id = %s",
                                 (old_run,))
                finish(video_ids[0], 1)
                finish(video_ids[1], 0)
                failed_run = uuid4()
                db.add_run(failed_run, video_ids[0])
                db.fail_run(failed_run, "Ошибка повтора")

                with TestClient(app) as client:
                    headers = {"X-API-Key": config.API_KEY}
                    self.assertEqual(client.get(f"/api/v1/workers/{worker_ids[0]}/rating").status_code, 401)
                    self.assertEqual(client.get(f"/api/v1/workers/{uuid4()}/rating",
                                                headers=headers).status_code, 404)
                    rating = client.get(f"/api/v1/workers/{worker_ids[0]}/rating", headers=headers).json()
                    self.assertEqual(rating["video_count"], 3)
                    self.assertEqual(rating["analyzed_video_count"], 2)
                    self.assertEqual(rating["violation_count"], 1)
                    self.assertEqual(rating["rating"], 66.7)
                    empty = client.get(f"/api/v1/workers/{worker_ids[1]}/rating", headers=headers).json()
                    self.assertEqual(empty["video_count"], 0)
                    self.assertIsNone(empty["rating"])
                    listed = client.get("/api/v1/workers", headers=headers).json()["items"]
                    self.assertEqual(next(item for item in listed if item["worker_id"] == str(worker_ids[0])), rating)

                    db.set_video_worker(video_ids[1], worker_ids[1])
                    moved = client.get(f"/api/v1/workers/{worker_ids[0]}/rating", headers=headers).json()
                    self.assertEqual((moved["video_count"], moved["analyzed_video_count"],
                                      moved["violation_count"], moved["rating"]), (2, 1, 1, 50.0))
                    receiving = client.get(f"/api/v1/workers/{worker_ids[1]}/rating", headers=headers).json()
                    self.assertEqual((receiving["video_count"], receiving["rating"]), (1, 100.0))
            finally:
                with db.connection() as conn:
                    for video_id in video_ids:
                        conn.execute("DELETE FROM videos WHERE id = %s", (video_id,))
                    for worker_id in worker_ids:
                        conn.execute("DELETE FROM worker WHERE id = %s", (worker_id,))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "нужны ffmpeg и ffprobe")
    def test_real_mov_through_jury_api(self):
        video_id = None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mov"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                            "-i", "testsrc2=size=160x120:rate=10", "-t", "2", "-c:v", "mpeg4",
                            "-q:v", "5", str(source)], check=True)
            with patch.object(config, "DATA_DIR", root / "data"), \
                 patch.object(config, "VIDEOS_DIR", root / "data" / "videos"), \
                 patch.object(config, "DATABASE_URL", os.environ["TEST_DATABASE_URL"]), \
                 patch.object(config, "VLM_BACKEND", "stub"), \
                 patch.object(config, "STUB_DEMO", False), \
                 patch("app.main.db.requeue_unfinished", return_value=[]):
                try:
                    with TestClient(app) as client, source.open("rb") as media:
                        headers = {"X-API-Key": config.API_KEY}
                        response = client.post("/api/v1/analyze", headers=headers,
                                               files={"file": ("source.mov", media, "video/quicktime")})
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(set(response.json()), {"job_id", "status"})
                        job_id = UUID(response.json()["job_id"])
                        run = db.get_run(job_id)
                        video_id = run["video_id"]
                        for _ in range(100):
                            result = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
                            if result["status"] == "done":
                                break
                            time.sleep(0.02)
                        self.assertEqual(result["status"], "done", result)
                        self.assertEqual(result["verdict"], "no_violation")
                        self.assertEqual(result["violations"], [])
                        metadata = client.get(f"/api/v1/videos/{video_id}", headers=headers).json()
                        self.assertEqual(metadata["duration_sec"], 2.0)
                        self.assertEqual(client.get(metadata["stream_url"],
                                                    headers={"Range": "bytes=0-9"}).status_code, 206)
                finally:
                    if video_id is not None:
                        with db.connection() as conn:
                            conn.execute("DELETE FROM videos WHERE id = %s", (video_id,))
