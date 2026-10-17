# ForteBank Compliance Intelligence · Frontend

The React interface uploads video files, tracks analysis jobs, and provides Investigations and Employees workspaces. Workers and their video associations are managed through the protected API.

## Run with the backend

Start PostgreSQL and FastAPI from the repository root, then run the frontend:

```sh
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/ui/*` and `/api/v1/*` to `http://127.0.0.1:8000` by default. To use another API origin, set `VITE_BACKEND_ORIGIN` in `front/.env.local`.

The protected worker and assignment routes require the same `API_KEY` as FastAPI. Put it in `front/.env.local` without a `VITE_` prefix:

```dotenv
API_KEY=the-same-key-used-by-fastapi
```

Vite adds this key from its server-side proxy; it is not exposed to the browser bundle. Restart Vite after changing the file. Production hosting needs an authenticated server proxy for protected routes; do not add the key to client-side environment variables.

The browser uploads unassigned videos through `POST /ui/analyze`, then polls `GET /ui/jobs/{job_id}`. When a worker is selected before upload, the file is sent through `POST /api/v1/workers/{worker_id}/videos` so the association is written with the video.

## Investigation history

The documented `/ui/*` routes do not expose a global video list. The protected `/api/v1/videos` route requires `X-API-Key`, which must not be shipped in browser code. The frontend therefore saves this browser's `video_id` and `job_id` pairs in `localStorage` and refreshes each job through the unauthenticated UI route. The video and analysis data themselves are stored by the backend. History is per browser until cookie or server-side authentication is added.

Investigation IDs are kept in this browser so the existing UI job route can restore its history. The Employees directory comes from the API. Worker assignments are stored with each video and can be changed from the investigation detail. Per-event decisions and reviewer comments remain review metadata in this browser.

The API exposes `GET /api/v1/workers`, `POST /api/v1/new-worker`, `GET /api/v1/workers/{worker_id}/videos`, and `PATCH /api/v1/videos/{video_id}/worker` for the directory and assignments. Worker profiles show their saved videos and leave a reserved space for a future performance index.

## Backend constraints

- Supported extensions: `.mov`, `.mp4`, `.m4v`.
- Maximum upload size: 200 MB by default (`MAX_UPLOAD_MB` on the backend).
- Upload starts analysis immediately. Upload progress is measured by browser bytes sent; analysis progress and stages come from the job endpoint.
- Playback uses the short-lived signed `stream_url` returned by the UI job endpoint.
- The backend defaults to `VLM_BACKEND=stub`; configure the local model service separately if real model analysis is required.

## Checks

```sh
npm run build
npm run lint
npx tsc --noEmit
```
