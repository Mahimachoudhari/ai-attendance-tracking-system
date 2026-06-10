-- ============================================================
-- AI Attendance System — PostgreSQL Schema
-- Requires: pgvector extension
-- Run: psql -U postgres -d attendance_db -f schema.sql
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- fast name search

-- ── Companies ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS companies (
    id         SERIAL PRIMARY KEY,
    code       VARCHAR(30)  UNIQUE NOT NULL,
    name       VARCHAR(200) NOT NULL,
    is_active  BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- ── Cameras (gate definitions) ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cameras (
    id          SERIAL PRIMARY KEY,
    company_id  INT         NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    camera_name VARCHAR(100) NOT NULL,
    gate_type   VARCHAR(10)  NOT NULL CHECK (gate_type IN ('entry','exit')),
    stream_url  TEXT,
    location    VARCHAR(200),
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- ── Employees ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS employees (
    id              SERIAL       PRIMARY KEY,
    employee_code   VARCHAR(50)  UNIQUE NOT NULL,
    name            VARCHAR(150) NOT NULL,
    company_id      INT          NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    department      VARCHAR(100),
    role            VARCHAR(100),
    face_embedding  VECTOR(128),          -- ArcFace 128-d, L2-normalised
    face_image_path TEXT,
    shift_start     TIME         NOT NULL DEFAULT '09:00',
    shift_end       TIME         NOT NULL DEFAULT '18:00',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    enrolled_at     TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- pgvector index for fast cosine similarity search
CREATE INDEX IF NOT EXISTS idx_emp_embedding
    ON employees USING ivfflat (face_embedding vector_cosine_ops)
    WITH (lists = 10);

CREATE INDEX IF NOT EXISTS idx_emp_company_active
    ON employees (company_id, is_active);

-- trigram index for fast name search
CREATE INDEX IF NOT EXISTS idx_emp_name_trgm
    ON employees USING gin (name gin_trgm_ops);

-- ── Attendance (one row per employee per day) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS attendance (
    id               BIGSERIAL    PRIMARY KEY,
    employee_id      INT          NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    employee_name    VARCHAR(150) NOT NULL,
    company_id       INT          NOT NULL REFERENCES companies(id),
    date             DATE         NOT NULL DEFAULT CURRENT_DATE,
    entry_time       TIMESTAMP,
    exit_time        TIMESTAMP,
    work_duration    INTERVAL GENERATED ALWAYS AS (exit_time - entry_time) STORED,
    entry_camera_id  INT          REFERENCES cameras(id),
    exit_camera_id   INT          REFERENCES cameras(id),
    entry_confidence FLOAT        CHECK (entry_confidence BETWEEN 0 AND 1),
    exit_confidence  FLOAT        CHECK (exit_confidence  BETWEEN 0 AND 1),
    status           VARCHAR(20)  NOT NULL DEFAULT 'present'
                     CHECK (status IN ('present','late','absent','half-day')),
    notes            TEXT,
    created_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    UNIQUE (employee_id, date)
);

CREATE INDEX IF NOT EXISTS idx_att_date         ON attendance (date);
CREATE INDEX IF NOT EXISTS idx_att_emp_date     ON attendance (employee_id, date);
CREATE INDEX IF NOT EXISTS idx_att_company_date ON attendance (company_id, date);
CREATE INDEX IF NOT EXISTS idx_att_status       ON attendance (status, date);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_attendance_updated_at ON attendance;
CREATE TRIGGER trg_attendance_updated_at
    BEFORE UPDATE ON attendance
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ── Attendance Events (raw log — entry & exit) ────────────────────────────────
CREATE TABLE IF NOT EXISTS attendance_events (
    id               BIGSERIAL    PRIMARY KEY,
    employee_id      INT          REFERENCES employees(id) ON DELETE SET NULL,
    employee_name    VARCHAR(150),
    company_id       INT          NOT NULL,
    camera_id        INT          REFERENCES cameras(id),
    event_type       VARCHAR(10)  NOT NULL CHECK (event_type IN ('entry','exit')),
    timestamp        TIMESTAMP    NOT NULL DEFAULT NOW(),
    confidence_score FLOAT        NOT NULL CHECK (confidence_score BETWEEN 0 AND 1),
    track_id         INT,
    face_bbox        JSONB,
    frame_path       TEXT
);

CREATE INDEX IF NOT EXISTS idx_evt_timestamp   ON attendance_events (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_evt_emp_ts      ON attendance_events (employee_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_evt_company_ts  ON attendance_events (company_id, timestamp DESC);

-- ── Security Alerts ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS security_alerts (
    id            BIGSERIAL    PRIMARY KEY,
    camera_id     INT          REFERENCES cameras(id),
    alert_type    VARCHAR(30)  NOT NULL
                  CHECK (alert_type IN ('unknown_person','spoofing_attempt','tailgating','forced_entry')),
    timestamp     TIMESTAMP    NOT NULL DEFAULT NOW(),
    confidence    FLOAT,
    snapshot_path TEXT,
    is_resolved   BOOLEAN      NOT NULL DEFAULT FALSE,
    resolved_at   TIMESTAMP,
    notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_alert_ts         ON security_alerts (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_alert_resolved   ON security_alerts (is_resolved, timestamp DESC);

-- ── Useful Views ───────────────────────────────────────────────────────────────

-- Today's live summary per company
CREATE OR REPLACE VIEW v_today_summary AS
SELECT
    c.id                                                                AS company_id,
    c.name                                                              AS company,
    COUNT(a.id) FILTER (WHERE a.entry_time IS NOT NULL)                 AS total_present,
    COUNT(a.id) FILTER (WHERE a.exit_time  IS NOT NULL)                 AS total_exited,
    COUNT(a.id) FILTER (WHERE a.status = 'late')                        AS total_late,
    ROUND(
        AVG(EXTRACT(EPOCH FROM a.work_duration)/3600)
        FILTER (WHERE a.work_duration IS NOT NULL)::NUMERIC, 2
    )                                                                   AS avg_hours_worked,
    (SELECT COUNT(*) FROM security_alerts sa
     WHERE sa.is_resolved = FALSE
       AND sa.timestamp::date = CURRENT_DATE)                           AS open_alerts
FROM companies c
LEFT JOIN attendance a ON a.company_id = c.id AND a.date = CURRENT_DATE
GROUP BY c.id, c.name;

-- Employee attendance history (last 30 days)
CREATE OR REPLACE VIEW v_employee_history AS
SELECT
    e.employee_code,
    e.name,
    e.department,
    a.date,
    a.entry_time,
    a.exit_time,
    TO_CHAR(a.work_duration, 'HH24:MI:SS') AS work_duration_fmt,
    a.status
FROM employees e
LEFT JOIN attendance a ON a.employee_id = e.id
WHERE a.date >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY e.name, a.date DESC;

-- ── Seed data ──────────────────────────────────────────────────────────────────
INSERT INTO companies (code, name)
VALUES ('ACME_IND', 'ACME Industries Ltd.')
ON CONFLICT (code) DO NOTHING;

INSERT INTO cameras (company_id, camera_name, gate_type, stream_url, location)
VALUES
    (1, 'Main Entry Gate — Cam 1', 'entry', 'demo/entry_gate.mp4', 'Gate A, North Side'),
    (1, 'Main Exit Gate  — Cam 2', 'exit',  'demo/exit_gate.mp4',  'Gate A, North Side')
ON CONFLICT DO NOTHING;