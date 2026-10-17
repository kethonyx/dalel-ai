-- Применить к существующему Docker volume; init.sql повторно не запускается.
CREATE TABLE IF NOT EXISTS worker (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE videos ADD COLUMN IF NOT EXISTS worker_id UUID REFERENCES worker(id);
CREATE INDEX IF NOT EXISTS videos_worker_created_idx ON videos (worker_id, created_at DESC);
