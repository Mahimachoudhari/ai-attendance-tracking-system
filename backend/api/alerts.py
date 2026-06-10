"""
backend/api/alerts.py
----------------------
REST endpoints:

  GET  /api/alerts           → open (unresolved) security alerts
  PUT  /api/alerts/{id}/resolve
  GET  /api/alerts/history   → all alerts (paginated)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from backend.services import database as db

router = APIRouter(prefix="/api/alerts", tags=["Security Alerts"])


@router.get("")
def get_open_alerts(limit: int = Query(default=20, ge=1, le=100)):
    """Return unresolved security alerts for the dashboard."""
    try:
        alerts = db.get_open_alerts(limit=limit)
        return {"alerts": alerts, "count": len(alerts)}
    except Exception as e:
        logger.error(f"get_open_alerts error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{alert_id}/resolve")
def resolve_alert(alert_id: int):
    try:
        db.resolve_alert(alert_id)
        return {"success": True, "message": f"Alert {alert_id} resolved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
def get_alert_history(
    page:     int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
):
    offset = (page - 1) * per_page
    try:
        with db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, camera_id, alert_type, timestamp,
                       confidence, is_resolved, notes
                FROM   security_alerts
                ORDER  BY timestamp DESC
                LIMIT  %s OFFSET %s
                """,
                (per_page, offset),
            )
            rows = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS total FROM security_alerts")
            total = cur.fetchone()["total"]
            cur.close()
        return {
            "alerts":   [dict(r) for r in rows],
            "total":    total,
            "page":     page,
            "per_page": per_page,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))