# ForteBank Compliance Intelligence · Frontend

Dark review workspace prototype for selecting video recordings, sending them to a video service, and browsing saved recordings in **Investigations**.

## Run locally

```sh
npm install
npm run dev
```

The upload endpoint is not configured by default. In that mode, the progress animation is a demo, and uploaded entries exist only in memory until the page is refreshed. No video is sent to a server or database.

## Connect the video API

Create a `.env.local` file in `front/` and set the endpoints supplied by the backend team:

```dotenv
VITE_VIDEO_UPLOAD_ENDPOINT=/api/videos
VITE_VIDEO_LIST_ENDPOINT=/api/videos
VITE_VIDEO_FORM_FIELD=video
```

`VITE_VIDEO_LIST_ENDPOINT` defaults to the upload endpoint, so one collection route can support both `POST` and `GET`. Set it separately if the backend uses different routes. `VITE_VIDEO_FORM_FIELD` defaults to `video`.

The frontend currently expects this contract; adjust `src/services/videoApi.ts` when the backend contract is confirmed:

- `POST` the upload endpoint with `multipart/form-data`, using the configured file field and an optional `durationSeconds` field.
- Return a JSON record with `id`, `fileName`, and `size`. `durationSeconds`, `createdAt`, and `videoUrl` are optional. `videoUrl` should be a browser-playable URL for the saved video.
- `GET` the list endpoint and return either an array of records or `{ "videos": [...] }` using the same record shape.
- Return a successful `2xx` response only after the file and record have been accepted. Upload progress reflects bytes sent by the browser; it does not represent server-side processing.

The UI distinguishes a successful service response from local demo entries. The analysis service is not connected, so a stored recording is not presented as analyzed.

## Checks

```sh
npm run build
npm run lint
npx tsc --noEmit
```
