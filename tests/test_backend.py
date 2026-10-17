"""Интеграция API с PostgreSQL; запускать с TEST_DATABASE_URL."""
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from app import config, db
from app.main import app


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "нужен TEST_DATABASE_URL")
class SavedVideoAPI(unittest.TestCase):
    def test_upload_result_reopen_and_seek(self):
        def fake_analyze(job_id, path, progress):
            progress("Анализ кадров", 0.5)
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
                    if video_id is not None:
                        with db.connection() as conn:
                            conn.execute("DELETE FROM videos WHERE id = %s", (UUID(video_id),))

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
