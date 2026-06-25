from __future__ import annotations
import base64, json
from datetime import datetime
import cv2
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from backend.config import cfg
from backend.core import embedding_store
from backend.core.ai_pipeline import process_frame, is_model_ready
from backend.core.websocket_manager import manager
from backend.services import database as db

router = APIRouter(tags=["Camera WebSocket"])
_gate_map: dict[int, str] = {1: "entry", 2: "exit"}


@router.websocket("/ws/camera/{camera_id}")
async def camera_ws(websocket: WebSocket, camera_id: int):
    await websocket.accept()
    gate_type = _gate_map.get(camera_id, "entry")
    logger.info(f"Camera {camera_id} ({gate_type}) connected")

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                msg = json.loads(raw)
            except Exception:
                continue

            if msg.get("type") != "frame":
                continue

            # Decode frame
            try:
                img_bytes = base64.b64decode(msg["data"])
                arr       = np.frombuffer(img_bytes, np.uint8)
                frame     = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            except Exception as e:
                logger.error(f"Frame decode error: {e}")
                continue

            if frame is None:
                continue

            ws_events  = []
            annotated  = frame.copy()
            now        = datetime.now()

            # AI pipeline — sirf tab chalao jab model ready ho
            if is_model_ready():
                embeddings = embedding_store.get()
                results, annotated = process_frame(
                    frame, embeddings, camera_id, gate_type
                )

                for r in results:
                    if r.is_spoof:
                        try:
                            db.insert_security_alert(
                                camera_id, "spoofing_attempt", r.spoof_score
                            )
                        except Exception:
                            pass
                        await manager.broadcast({
                            "type":      "security_alert",
                            "alert":     "spoofing_attempt",
                            "camera_id": camera_id,
                            "timestamp": now.isoformat(),
                        })
                        continue

                    if not r.is_match or r.employee_id is None:
                        continue

                    # Known employee — DB mein save karo
                    try:
                        db.insert_attendance_event(
                            employee_id=r.employee_id,
                            employee_name=r.employee_name,
                            company_id=cfg.company_id,
                            camera_id=camera_id,
                            event_type=gate_type,
                            timestamp=now,
                            confidence=r.similarity,
                            track_id=None,
                            face_bbox=None,
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
                    except Exception as e:
                        logger.error(f"DB error: {e}")

                    event = {
                        "type":          "attendance_event",
                        "gate":          gate_type,
                        "employee_id":   r.employee_id,
                        "employee_name": r.employee_name,
                        "employee_code": r.employee_code,
                        "confidence":    r.similarity,
                        "timestamp":     now.isoformat(),
                        "proc_ms":       r.proc_ms,
                        "camera_id":     camera_id,
                    }
                    ws_events.append(event)
                    await manager.broadcast(event)

            # ── HAMESHA annotated frame bhejo ──────────────────
            _, buf = cv2.imencode(
                ".jpg", annotated,
                [cv2.IMWRITE_JPEG_QUALITY, cfg.jpeg_quality],
            )
            b64 = base64.b64encode(buf).decode("ascii")

            await websocket.send_json({
                "type":       "annotated_frame",
                "data":       b64,
                "events":     ws_events,
                "proc_ms":    0,
                "face_count": len(ws_events),
            })

    except WebSocketDisconnect:
        logger.info(f"Camera {camera_id} disconnected")
    except Exception as e:
        logger.error(f"Camera {camera_id} error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)