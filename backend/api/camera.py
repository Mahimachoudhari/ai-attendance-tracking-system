"""
backend/api/camera.py
----------------------
WebSocket endpoint for live camera frame processing.

  WS /ws/camera/{camera_id}

Protocol (client → server):
  { "type": "frame", "data": "<base64 JPEG>" }

Protocol (server → client):
  { "type": "annotated_frame",
    "data": "<base64 JPEG with bboxes>",
    "events": [ {...} ],
    "proc_ms": 42.3,
    "face_count": 3 }

Also broadcasts every attendance event to all dashboard WS clients.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime

import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from backend.config import cfg
from backend.core import embedding_store
from backend.core.ai_pipeline import process_frame
from backend.core.websocket_manager import manager
from backend.services import database as db
from backend.services import kafka_producer as kp

router = APIRouter(tags=["Camera WebSocket"])

# Map camera_id → gate_type (loaded once from DB, cached here)
_gate_map: dict[int, str] = {1: "entry", 2: "exit"}


async def _get_gate_type(camera_id: int) -> str:
    """Resolve gate type for a camera_id. Falls back to env map."""
    if camera_id in _gate_map:
        return _gate_map[camera_id]
    try:
        with db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT gate_type FROM cameras WHERE id = %s AND is_active = TRUE",
                (camera_id,),
            )
            row = cur.fetchone()
            cur.close()
        if row:
            _gate_map[camera_id] = row["gate_type"]
            return row["gate_type"]
    except Exception:
        pass
    return "entry" if camera_id % 2 == 1 else "exit"


@router.websocket("/ws/camera/{camera_id}")
async def camera_ws(websocket: WebSocket, camera_id: int):
    """
    Accepts base64 JPEG frames from a camera client (browser / demo script).
    Runs the full AI pipeline on each frame and returns:
      - annotated frame
      - recognition events
      - per-frame processing time
    """
    await websocket.accept()
    gate_type = await _get_gate_type(camera_id)
    logger.info(f"Camera {camera_id} ({gate_type}) WebSocket connected")

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") != "frame":
                continue

            # ── Decode frame ─────────────────────────────────────────────────
            try:
                img_bytes = base64.b64decode(msg["data"])
                arr       = np.frombuffer(img_bytes, np.uint8)
                frame     = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            except Exception as e:
                logger.warning(f"Frame decode error cam{camera_id}: {e}")
                continue

            if frame is None:
                continue

            # ── AI Pipeline ───────────────────────────────────────────────────
            embeddings = embedding_store.get()
            results, annotated = process_frame(frame, embeddings, camera_id, gate_type)

            # ── Persist + broadcast events ────────────────────────────────────
            ws_events: list[dict] = []
            now = datetime.now()

            for r in results:
                if r.is_spoof:
                    # Security alert
                    try:
                        db.insert_security_alert(
                            camera_id=camera_id,
                            alert_type="spoofing_attempt",
                            confidence=r.spoof_score,
                        )
                    except Exception:
                        pass

                    alert_payload = {
                        "type":      "security_alert",
                        "alert":     "spoofing_attempt",
                        "camera_id": camera_id,
                        "timestamp": now.isoformat(),
                        "confidence": r.spoof_score,
                    }
                    await manager.broadcast(alert_payload)
                    kp.publish_alert(alert_payload)
                    continue

                if not r.is_match or r.employee_id is None:
                    # Unknown person
                    try:
                        db.insert_security_alert(
                            camera_id=camera_id,
                            alert_type="unknown_person",
                            confidence=r.similarity,
                        )
                    except Exception:
                        pass
                    continue

                # ── Known employee: record event ──────────────────────────────
                try:
                    db.insert_attendance_event(
                        employee_id=r.employee_id,
                        employee_name=r.employee_name,
                        company_id=cfg.company_id,
                        camera_id=camera_id,
                        event_type=gate_type,
                        timestamp=now,
                        confidence=r.similarity,
                        track_id=r.face.track_id,
                        face_bbox={
                            "x1": r.face.bbox[0], "y1": r.face.bbox[1],
                            "x2": r.face.bbox[2], "y2": r.face.bbox[3],
                        },
                    )
                    db.upsert_attendance(
                        employee_id=r.employee_id,
                        employee_name=r.employee_name,
                        company_id=cfg.company_id,
                        camera_id=camera_id,
                        event_type=gate_type,
                        timestamp=now,
                        confidence=r.similarity,
                    )
                except Exception as db_err:
                    logger.error(f"DB write error: {db_err}")

                event = {
                    "type":          "attendance_event",
                    "gate":          gate_type,
                    "employee_id":   r.employee_id,
                    "employee_name": r.employee_name,
                    "employee_code": r.employee_code,
                    "confidence":    r.similarity,
                    "timestamp":     now.isoformat(),
                    "is_spoof":      False,
                    "proc_ms":       r.proc_ms,
                    "camera_id":     camera_id,
                }
                ws_events.append(event)
                await manager.broadcast(event)

                # Kafka publish (non-blocking)
                kp.publish_event(
                    kp.build_event_payload(
                        employee_id=r.employee_id,
                        employee_name=r.employee_name,
                        employee_code=r.employee_code,
                        camera_id=camera_id,
                        gate_type=gate_type,
                        confidence=r.similarity,
                        timestamp=now,
                        track_id=r.face.track_id,
                    )
                )

            # ── Send annotated frame back to camera client ────────────────────
            _, buf    = cv2.imencode(
                ".jpg", annotated,
                [cv2.IMWRITE_JPEG_QUALITY, cfg.jpeg_quality],
            )
            b64_frame = base64.b64encode(buf).decode("ascii")

            await websocket.send_json({
                "type":       "annotated_frame",
                "data":       b64_frame,
                "events":     ws_events,
                "proc_ms":    results[0].proc_ms if results else 0.0,
                "face_count": len(results),
            })

    except WebSocketDisconnect:
        logger.info(f"Camera {camera_id} disconnected")
    except Exception as e:
        logger.error(f"Camera {camera_id} WS error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    """
    Dashboard clients connect here to receive real-time attendance events.
    Server → client only; client sends keep-alive pings.
    """
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()   # absorb keep-alive pings
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)