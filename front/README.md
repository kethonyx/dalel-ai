# ForteBank Compliance Intelligence · Frontend

The React interface uploads video files to the FastAPI browser route, tracks analysis jobs, and provides an Investigations library with video posters, filters, case details, and human review controls.

## Run with the backend

Start PostgreSQL and FastAPI from the repository root, then run the frontend:

```sh
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/ui/*` and signed `/api/v1/videos/*/stream` requests to `http://127.0.0.1:8000` by default. To use another backend origin, set `VITE_BACKEND_ORIGIN` in `front/.env.local` and restart Vite.

The browser calls `POST /ui/analyze` with multipart field `file`, then polls `GET /ui/jobs/{job_id}` for backend progress and results. The API key is never included in the frontend.

## Investigation history

The documented `/ui/*` routes do not expose a global video list. The protected `/api/v1/videos` route requires `X-API-Key`, which must not be shipped in browser code. The frontend therefore saves this browser's `video_id` and `job_id` pairs in `localStorage` and refreshes each job through the unauthenticated UI route. The video and analysis data themselves are stored by the backend. History is per browser until cookie or server-side authentication is added.

Employee assignment, per-event Confirm/Dismiss decisions, and reviewer comments are also stored locally under each `job_id`. They are manual review metadata and are not sent to the backend yet. Failed jobs can be removed from the browser's library; this does not delete the stored backend video.

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
