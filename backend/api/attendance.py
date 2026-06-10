"""
backend/api/attendance.py
--------------------------
REST endpoints:

  GET  /api/attendance/today       → summary + records
  GET  /api/attendance/live        → last N raw events
  GET  /api/attendance/report      → date-range CSV download
  POST /api/attendance/manual      → manual mark (fallback)
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger

from backend.config import cfg
from backend.services import database as db

router = APIRouter(prefix="/api/attendance", tags=["Attendance"])


# ── Today's summary + records ────────────────────────────────────────────────

@router.get("/today")
def get_today():
    """Full attendance dashboard data for today."""
    try:
        summary = db.get_today_summary(cfg.company_id)
        records = db.get_today_records(cfg.company_id)
        return {
            "date":    date.today().isoformat(),
            "summary": summary,
            "records": records,
        }
    except Exception as e:
        logger.error(f"get_today error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Live event stream (last N) ────────────────────────────────────────────────

@router.get("/live")
def get_live_events(limit: int = Query(default=20, ge=1, le=100)):
    """Most recent attendance_events rows for the dashboard ticker."""
    try:
        events = db.get_live_events(limit=limit)
        return {"events": events, "count": len(events)}
    except Exception as e:
        logger.error(f"get_live_events error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── CSV report download ────────────────────────────────────────────────────────

@router.get("/report")
def download_report(
    from_date: date = Query(default=date.today()),
    to_date:   date = Query(default=date.today()),
):
    """
    Download attendance report as CSV for a date range.
    Example: GET /api/attendance/report?from_date=2024-01-01&to_date=2024-01-31
    """
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be ≤ to_date")

    try:
        with db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    e.employee_code,
                    e.name,
                    e.department,
                    e.role,
                    a.date,
                    a.entry_time,
                    a.exit_time,
                    TO_CHAR(a.work_duration, 'HH24:MI:SS') AS work_duration,
                    a.entry_confidence,
                    a.exit_confidence,
                    a.status
                FROM attendance a
                JOIN employees  e ON e.id = a.employee_id
                WHERE a.date BETWEEN %s AND %s
                  AND a.company_id = %s
                ORDER BY a.date, e.name
                """,
                (from_date, to_date, cfg.company_id),
            )
            rows = cur.fetchall()
            cur.close()
    except Exception as e:
        logger.error(f"report query error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # Build CSV in memory
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Employee Code", "Name", "Department", "Role",
        "Date", "Entry Time", "Exit Time", "Work Duration",
        "Entry Confidence", "Exit Confidence", "Status",
    ])
    for r in rows:
        writer.writerow([
            r["employee_code"], r["name"], r["department"], r["role"],
            r["date"], r["entry_time"], r["exit_time"], r["work_duration"],
            f"{(r['entry_confidence'] or 0):.2%}",
            f"{(r['exit_confidence']  or 0):.2%}",
            r["status"],
        ])

    buf.seek(0)
    filename = f"attendance_{from_date}_{to_date}.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Manual mark (admin fallback) ───────────────────────────────────────────────

@router.post("/manual")
def manual_mark(
    employee_code: str,
    event_type:    str = Query(pattern="^(entry|exit)$"),
    camera_id:     int = 1,
):
    """
    Manually record an entry or exit event.
    Used by admin when camera fails.
    """
    try:
        with db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, name FROM employees WHERE employee_code = %s AND is_active = TRUE",
                (employee_code,),
            )
            emp = cur.fetchone()
            cur.close()

        if not emp:
            raise HTTPException(status_code=404, detail=f"Employee '{employee_code}' not found")

        now = datetime.now()
        db.insert_attendance_event(
            employee_id=emp["id"],
            employee_name=emp["name"],
            company_id=cfg.company_id,
            camera_id=camera_id,
            event_type=event_type,
            timestamp=now,
            confidence=1.0,
        )
        db.upsert_attendance(
            employee_id=emp["id"],
            employee_name=emp["name"],
            company_id=cfg.company_id,
            camera_id=camera_id,
            event_type=event_type,
            timestamp=now,
            confidence=1.0,
        )
        return {"success": True, "message": f"{event_type.upper()} recorded for {emp['name']}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"manual_mark error: {e}")
        raise HTTPException(status_code=500, detail=str(e))