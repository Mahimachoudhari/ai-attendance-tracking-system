"""
backend/services/database.py
-----------------------------
PostgreSQL connection pool + all database operations.
Uses psycopg2 with a thread-safe connection pool.
"""

from __future__ import annotations
import ast
import threading
from contextlib import contextmanager
from datetime import date, datetime
from typing import Optional, Generator

import numpy as np
import psycopg2
import psycopg2.extras
import psycopg2.pool
from loguru import logger

from backend.config import cfg

# ── Connection Pool ────────────────────────────────────────────────────────────

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_pool_lock = threading.Lock()


def init_pool() -> None:
    """Create the connection pool. Called once at app startup."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            return
        try:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=cfg.db_pool_min,
                maxconn=cfg.db_pool_max,
                host=cfg.db_host,
                port=cfg.db_port,
                dbname=cfg.db_name,
                user=cfg.db_user,
                password=cfg.db_password,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
            logger.info(
                f"DB pool created: {cfg.db_pool_min}-{cfg.db_pool_max} connections "
                f"→ {cfg.db_host}:{cfg.db_port}/{cfg.db_name}"
            )
        except Exception as e:
            logger.error(f"DB pool init failed: {e}")
            raise


def close_pool() -> None:
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("DB pool closed")


@contextmanager
def get_conn() -> Generator:
    """Context manager: borrow a connection from pool, return on exit."""
    if _pool is None:
        init_pool()
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


# ── Health check ────────────────────────────────────────────────────────────────

def ping() -> bool:
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
        return True
    except Exception:
        return False


# ── Employee queries ────────────────────────────────────────────────────────────

def get_today_summary(company_id: int) -> dict:

    today = date.today().isoformat()

    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE entry_time IS NOT NULL) AS present,
                COUNT(*) FILTER (WHERE exit_time IS NOT NULL) AS exited,
                COUNT(*) FILTER (WHERE status = 'late') AS late,
                COUNT(*) FILTER (WHERE status = 'absent') AS absent,

                ROUND(
                    AVG(
                        EXTRACT(
                            EPOCH FROM (
                                exit_time - entry_time
                            )
                        ) / 3600.0
                    )
                    FILTER (
                        WHERE entry_time IS NOT NULL
                        AND exit_time IS NOT NULL
                    )::numeric,
                    2
                ) AS avg_hours

            FROM attendance
            WHERE date = %s
            AND company_id = %s
            """,
            (today, company_id)
        )

        row = cur.fetchone()
        cur.close()

    return dict(row) if row else {}



def get_employee_embeddings(company_id: int):

    with get_conn() as conn:

        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                id,
                name,
                employee_code,
                face_embedding
            FROM employees
            WHERE company_id = %s
            AND is_active = TRUE
            AND face_embedding IS NOT NULL
            """,
            (company_id,)
        )

        rows = cur.fetchall()
        cur.close()

    result = {}

    for r in rows:

        try:

            emb = r["face_embedding"]

            if isinstance(emb, str):
                emb = ast.literal_eval(emb)

            emb = np.array(
                emb,
                dtype=np.float32
            )

            result[r["id"]] = (
                r["name"],
                r["employee_code"],
                emb
            )

        except Exception as e:

            logger.error(
                f"Embedding parse failed for "
                f"{r['id']} : {e}"
            )

    return result

# ── Attendance queries ──────────────────────────────────────────────────────────

def insert_attendance_event(
    employee_id:    int,
    employee_name:  str,
    company_id:     int,
    camera_id:      int,
    event_type:     str,
    timestamp:      datetime,
    confidence:     float,
    track_id:       Optional[int] = None,
    face_bbox:      Optional[dict] = None,
) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO attendance_events
                (employee_id, employee_name, company_id, camera_id,
                 event_type, timestamp, confidence_score, track_id, face_bbox)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                employee_id, employee_name, company_id, camera_id,
                event_type, timestamp, confidence, track_id,
                psycopg2.extras.Json(face_bbox) if face_bbox else None,
            ),
        )
        row = cur.fetchone()
        cur.close()
    return row["id"]


def upsert_attendance(
    employee_id:   int,
    employee_name: str,
    company_id:    int,
    camera_id:     int,
    event_type:    str,
    timestamp:     datetime,
    confidence:    float,
) -> None:
    today = timestamp.date()
    with get_conn() as conn:
        cur = conn.cursor()

        if event_type == "entry":
            cur.execute(
                """
                INSERT INTO attendance
                    (employee_id, employee_name, company_id, date,
                     entry_time, entry_camera_id, entry_confidence, status)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s,
                     CASE WHEN %s::time > (
                         SELECT shift_start + INTERVAL '15 minutes'
                         FROM employees WHERE id = %s
                     ) THEN 'late' ELSE 'present' END)
                ON CONFLICT (employee_id, date) DO UPDATE
                    SET entry_time        = EXCLUDED.entry_time,
                        entry_camera_id   = EXCLUDED.entry_camera_id,
                        entry_confidence  = EXCLUDED.entry_confidence,
                        status            = EXCLUDED.status,
                        updated_at        = NOW()
                WHERE attendance.entry_time IS NULL
                """,
                (
                    employee_id, employee_name, company_id, today,
                    timestamp, camera_id, confidence,
                    timestamp.time(), employee_id,
                ),
            )
        else:  # exit
            cur.execute(
                """
                INSERT INTO attendance
                    (employee_id, employee_name, company_id, date,
                     exit_time, exit_camera_id, exit_confidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (employee_id, date) DO UPDATE
                    SET exit_time       = EXCLUDED.exit_time,
                        exit_camera_id  = EXCLUDED.exit_camera_id,
                        exit_confidence = EXCLUDED.exit_confidence,
                        updated_at      = NOW()
                """,
                (employee_id, employee_name, company_id, today,
                 timestamp, camera_id, confidence),
            )
        cur.close()


def get_today_summary(company_id: int) -> dict:
    today = date.today().isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE entry_time IS NOT NULL)               AS present,
                COUNT(*) FILTER (WHERE exit_time  IS NOT NULL)               AS exited,
                COUNT(*) FILTER (WHERE status = 'late')                      AS late,
                COUNT(*) FILTER (WHERE status = 'absent')                    AS absent,
                ROUND(
                    AVG(EXTRACT(EPOCH FROM work_duration) / 3600.0)
                    FILTER (WHERE work_duration IS NOT NULL)::numeric, 2
                )                                                             AS avg_hours
            FROM attendance
            WHERE date = %s AND company_id = %s
            """,
            (today, company_id),
        )
        row = cur.fetchone()
        cur.close()
    return dict(row) if row else {}


def get_today_records(company_id: int, limit: int = 200) -> list[dict]:

    today = date.today().isoformat()

    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                a.id,
                a.employee_id,
                a.employee_name,
                e.employee_code,
                e.department,
                a.date,
                a.entry_time,
                a.exit_time,

                CASE
                    WHEN a.entry_time IS NOT NULL
                     AND a.exit_time IS NOT NULL
                    THEN
                        TO_CHAR(
                            a.exit_time - a.entry_time,
                            'HH24:MI:SS'
                        )
                    ELSE NULL
                END AS work_duration,

                a.status

            FROM attendance a
            JOIN employees e
                ON e.id = a.employee_id

            WHERE a.date = %s
            AND a.company_id = %s

            ORDER BY a.entry_time DESC NULLS LAST
            LIMIT %s
            """,
            (
                today,
                company_id,
                limit
            )
        )

        rows = cur.fetchall()
        cur.close()

    return [dict(r) for r in rows]


def get_live_events(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ae.id, ae.employee_id, ae.employee_name,
                   e.employee_code,
                   ae.camera_id, ae.event_type AS gate_type,
                   ae.timestamp, ae.confidence_score AS confidence,
                   ae.track_id
            FROM   attendance_events ae
            LEFT   JOIN employees e ON e.id = ae.employee_id
            ORDER  BY ae.timestamp DESC
            LIMIT  %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        cur.close()
    return [dict(r) for r in rows]


# ── Security alerts ─────────────────────────────────────────────────────────────

def insert_security_alert(
    camera_id:   int,
    alert_type:  str,
    confidence:  float,
    notes:       Optional[str] = None,
) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO security_alerts (camera_id, alert_type, confidence, notes)
            VALUES (%s, %s, %s, %s)
            """,
            (camera_id, alert_type, confidence, notes),
        )
        cur.close()


def get_open_alerts(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, camera_id, alert_type, timestamp,
                   confidence, is_resolved, notes
            FROM   security_alerts
            WHERE  is_resolved = FALSE
            ORDER  BY timestamp DESC
            LIMIT  %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        cur.close()
    return [dict(r) for r in rows]


def resolve_alert(alert_id: int) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE security_alerts SET is_resolved = TRUE WHERE id = %s",
            (alert_id,),
        )
        cur.close()