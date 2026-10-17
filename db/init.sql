-- POSTGRES_DB=dalel создаёт базу при первом запуске контейнера.
-- Этот файл создаёт схему в ней. Выполняется один раз на пустом Docker volume.

CREATE TABLE worker (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE videos (
    id UUID PRIMARY KEY,
    worker_id UUID REFERENCES worker(id),
    storage_key TEXT NOT NULL UNIQUE,
    original_name TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    duration_sec DOUBLE PRECISION NOT NULL CHECK (duration_sec > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX videos_worker_created_idx ON videos (worker_id, created_at DESC);

CREATE TABLE analysis_runs (
    id UUID PRIMARY KEY,
    video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'done', 'failed')),
    stage TEXT NOT NULL DEFAULT 'В очереди',
    progress DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (progress >= 0 AND progress <= 1),
    verdict TEXT CHECK (verdict IN ('violation', 'no_violation')),
    result_json JSONB,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX analysis_runs_video_created_idx ON analysis_runs (video_id, created_at DESC);

CREATE TABLE frame_analyses (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    frame_index INTEGER NOT NULL CHECK (frame_index >= 0),
    timestamp_sec DOUBLE PRECISION NOT NULL CHECK (timestamp_sec >= 0),
    analysis_json JSONB NOT NULL,
    UNIQUE (run_id, frame_index)
);
CREATE INDEX frame_analyses_run_time_idx ON frame_analyses (run_id, timestamp_sec);

CREATE TABLE events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    event_index INTEGER NOT NULL CHECK (event_index >= 0),
    timecode_sec DOUBLE PRECISION NOT NULL CHECK (timecode_sec >= 0),
    type TEXT NOT NULL,
    description TEXT NOT NULL,
    rule_json JSONB,
    UNIQUE (run_id, event_index)
);
CREATE INDEX events_run_time_idx ON events (run_id, timecode_sec);
