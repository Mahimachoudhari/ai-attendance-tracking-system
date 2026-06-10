"""
backend/api/employees.py
--------------------------
REST endpoints:

  GET    /api/employees            → list all employees
  GET    /api/employees/{id}       → single employee detail
  POST   /api/employees/enroll     → create employee + extract face embedding
  PUT    /api/employees/{id}/deactivate
  DELETE /api/employees/{id}
"""

from __future__ import annotations

import io
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from loguru import logger

from backend.config import cfg
from backend.core import embedding_store
from backend.core.ai_pipeline import detect_faces, filter_quality, enhance_low_light
from backend.services import database as db

router = APIRouter(prefix="/api/employees", tags=["Employees"])


# ── List all ──────────────────────────────────────────────────────────────────

@router.get("")
def list_employees():
    try:
        employees = db.get_all_employees(cfg.company_id)
        return {"employees": employees, "count": len(employees)}
    except Exception as e:
        logger.error(f"list_employees error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Single employee ────────────────────────────────────────────────────────────

@router.get("/{employee_id}")
def get_employee(employee_id: int):
    try:
        with db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, employee_code, name, department, role,
                       is_active, enrolled_at, shift_start, shift_end
                FROM   employees
                WHERE  id = %s AND company_id = %s
                """,
                (employee_id, cfg.company_id),
            )
            row = cur.fetchone()
            cur.close()
        if not row:
            raise HTTPException(status_code=404, detail="Employee not found")
        return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Enroll new employee with face photo ───────────────────────────────────────

@router.post("/enroll")
async def enroll_employee(
    employee_code: str      = Form(...),
    name:          str      = Form(...),
    department:    str      = Form(""),
    role:          str      = Form(""),
    shift_start:   str      = Form("09:00"),
    shift_end:     str      = Form("18:00"),
    photo:         UploadFile = File(..., description="Clear frontal face photo (JPEG/PNG)"),
):
    """
    Enroll a new employee:
    1. Receive frontal face photo.
    2. Run RetinaFace detection.
    3. Extract ArcFace 128-d embedding.
    4. Save employee + embedding to DB.
    5. Hot-reload embedding store.
    """
    # ── Read & decode image ───────────────────────────────────────────────────
    raw   = await photo.read()
    arr   = np.frombuffer(raw, np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if frame is None:
        raise HTTPException(status_code=400, detail="Could not decode image. Send JPEG or PNG.")

    # ── Detect face ───────────────────────────────────────────────────────────
    faces = detect_faces(frame)
    if not faces:
        raise HTTPException(
            status_code=422,
            detail="No face detected in photo. Use a clear, well-lit frontal photo.",
        )

    # Pick highest-confidence face
    face = max(faces, key=lambda f: f.det_confidence)
    face = filter_quality(face, frame)

    if not face.quality_ok:
        raise HTTPException(
            status_code=422,
            detail=f"Face quality too low: {face.reject_reason}. Retake photo.",
        )

    if face.embedding is None:
        raise HTTPException(
            status_code=422,
            detail="Could not extract face embedding. Ensure face is clearly visible.",
        )

    # ── Enhance crop (optional, improves embedding quality) ───────────────────
    x1, y1, x2, y2 = face.bbox
    crop = frame[max(y1, 0):y2, max(x1, 0):x2]
    enhance_low_light(crop)    # run but use original embedding (already extracted)

    embedding: list[float] = face.embedding.tolist()

    # ── Persist to DB ─────────────────────────────────────────────────────────
    try:
        employee_id = db.create_employee(
            employee_code=employee_code,
            name=name,
            company_id=cfg.company_id,
            department=department or None,
            role=role or None,
        )
        db.upsert_employee_embedding(employee_id, embedding)
    except Exception as e:
        logger.error(f"enroll DB error: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

    # ── Hot-reload embedding store ────────────────────────────────────────────
    emb_arr = np.array(embedding, dtype=np.float32)
    embedding_store.add(employee_id, name, employee_code, emb_arr)

    logger.info(f"Enrolled: {name} ({employee_code}) id={employee_id}")
    return {
        "success":     True,
        "employee_id": employee_id,
        "message":     f"{name} enrolled successfully.",
        "confidence":  round(face.det_confidence, 4),
    }


# ── Deactivate employee ────────────────────────────────────────────────────────

@router.put("/{employee_id}/deactivate")
def deactivate_employee(employee_id: int):
    try:
        with db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE employees SET is_active = FALSE WHERE id = %s AND company_id = %s",
                (employee_id, cfg.company_id),
            )
            affected = cur.rowcount
            cur.close()
        if affected == 0:
            raise HTTPException(status_code=404, detail="Employee not found")
        from backend.services.cache import remove_embedding
        remove_embedding(employee_id)
        embedding_store.reload()
        return {"success": True, "message": "Employee deactivated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Delete employee (hard) ─────────────────────────────────────────────────────

@router.delete("/{employee_id}")
def delete_employee(employee_id: int):
    try:
        with db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM employees WHERE id = %s AND company_id = %s",
                (employee_id, cfg.company_id),
            )
            affected = cur.rowcount
            cur.close()
        if affected == 0:
            raise HTTPException(status_code=404, detail="Employee not found")
        from backend.services.cache import remove_embedding
        remove_embedding(employee_id)
        return {"success": True, "message": "Employee deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))