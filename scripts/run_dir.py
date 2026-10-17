"""Прогнать папку роликов через API и записать результаты + время обработки.

    python scripts/run_dir.py videos/ --url http://127.0.0.1:8000 --key $API_KEY

Нужен, чтобы заранее замерить время на самом длинном ролике (лимит жюри 5 минут)
и подбирать пороги по разметке. Результат: results.jsonl рядом со скриптом запуска.
"""
import argparse
import json
import time
from pathlib import Path

import httpx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--key", required=True)
    ap.add_argument("--out", type=Path, default=Path("results.jsonl"))
    args = ap.parse_args()

    headers = {"X-API-Key": args.key}
    videos = sorted(args.folder.glob("*.mov"))
    with httpx.Client(base_url=args.url, headers=headers, timeout=60) as client, args.out.open("w") as out:
        for video in videos:
            t0 = time.monotonic()
            with video.open("rb") as f:
                job = client.post("/api/v1/analyze", files={"file": (video.name, f, "video/quicktime")})
            job.raise_for_status()
            job_id = job.json()["job_id"]
            while True:
                data = client.get(f"/api/v1/jobs/{job_id}").json()
                if data["status"] != "processing":
                    break
                time.sleep(1)
            elapsed = time.monotonic() - t0
            for v in data.get("violations", []):
                v["evidence_frames"] = f"<{len(v['evidence_frames'])} frames>"  # не раздуваем файл
            out.write(json.dumps({"file": video.name, "seconds": round(elapsed, 1), **data}, ensure_ascii=False) + "\n")
            print(f"{video.name}: {data['status']} {data.get('verdict', '')} {elapsed:.1f}s")


if __name__ == "__main__":
    main()
