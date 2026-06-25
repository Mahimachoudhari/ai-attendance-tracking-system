
"""
backend/core/ai_pipeline.py
----------------------------
PRODUCTION AI pipeline — NO mock data, NO fake events.

Agar InsightFace load na ho to pipeline empty list return karta hai.
Koi bhi fake face ya random embedding generate NAHI hoga.

Steps:
  1. Face Detection      – RetinaFace (InsightFace)
  2. Quality Filter      – size / blur / yaw
  3. Image Enhancement   – CLAHE + gamma (low-light cameras)
  4. Anti-Spoof Check    – passive liveness
  5. Employee Matching   – cosine similarity
  6. Annotate Frame      – bounding boxes draw
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from loguru import logger

from backend.config import cfg

# ── Model singleton ────────────────────────────────────────────
_model_lock  = threading.Lock()
_app         = None          # InsightFace FaceAnalysis app
_model_ready = False         # True only when real model loaded


def _load_model():
    global _app, _model_ready
    if _app is not None:
        return _app
    with _model_lock:
        if _app is not None:
            return _app
        try:
            from insightface.app import FaceAnalysis
            providers = (
                ["CUDAExecutionProvider", "CPUExecutionProvider"]
                if cfg.gpu_id >= 0
                else ["CPUExecutionProvider"]
            )
            app = FaceAnalysis(name='buffalo_l', providers=providers)
            app.prepare(ctx_id=cfg.gpu_id, det_size=(640, 640))
            _app         = app
            _model_ready = True
            logger.info(f"✅ InsightFace loaded: {cfg.model_name} (GPU={cfg.gpu_id})")
        except Exception as e:
            # Model load nahi hua — _app = None rakhenge
            # Koi mock/fake data NAHI banayenge
            _app         = None
            _model_ready = False
            logger.error(
                f"❌ InsightFace load failed: {e}\n"
                f"   Real attendance kaam nahi karega jab tak model load na ho.\n"
                f"   Fix: pip install insightface onnxruntime"
            )
    return _app


def is_model_ready() -> bool:
    """Returns True only when real AI model is loaded."""
    return _model_ready


# ── Dataclasses ────────────────────────────────────────────────

@dataclass
class DetectedFace:
    bbox:           tuple[int, int, int, int]
    landmarks:      Optional[np.ndarray]
    det_confidence: float
    embedding:      Optional[np.ndarray] = None
    track_id:       Optional[int]        = None
    quality_ok:     bool                 = True
    reject_reason:  str                  = ""


@dataclass
class RecognitionResult:
    employee_id:   Optional[int]
    employee_name: Optional[str]
    employee_code: Optional[str]
    similarity:    float
    is_match:      bool
    face:          DetectedFace
    is_spoof:      bool  = False
    spoof_score:   float = 0.0
    proc_ms:       float = 0.0


# ── Step 1: Face Detection ─────────────────────────────────────

def detect_faces(frame: np.ndarray) -> list[DetectedFace]:
    """
    Real face detection using RetinaFace.
    Agar model load nahi hua → empty list return karta hai.
    KOI FAKE FACE NAHI BANEGA.
    """
    app = _load_model()

    # Model available nahi → koi face nahi detect hoga
    if app is None:
        return []

    try:
        raw_faces = app.get(frame)
    except Exception as e:
        logger.error(f"Face detection error: {e}")
        return []

    results: list[DetectedFace] = []
    for f in raw_faces:
        x1, y1, x2, y2 = (int(v) for v in f.bbox)
        results.append(DetectedFace(
            bbox=(x1, y1, x2, y2),
            landmarks=getattr(f, "kps", None),
            det_confidence=float(f.det_score),
            embedding=getattr(f, "embedding", None),
        ))
    return results


# ── Step 2: Quality Filter ─────────────────────────────────────

def filter_quality(face: DetectedFace, frame: np.ndarray) -> DetectedFace:
    """Reject faces that are too small, blurry, or extreme-angle."""
    x1, y1, x2, y2 = face.bbox
    w, h = x2 - x1, y2 - y1

    # Size check
    if w < cfg.min_face_size or h < cfg.min_face_size:
        face.quality_ok    = False
        face.reject_reason = f"too_small ({w}×{h}px)"
        return face

    # Crop validity
    crop = frame[max(y1, 0):y2, max(x1, 0):x2]
    if crop.size == 0:
        face.quality_ok    = False
        face.reject_reason = "empty_crop"
        return face

    # Blur check
    gray       = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    if blur_score < cfg.blur_threshold:
        face.quality_ok    = False
        face.reject_reason = f"blurry (score={blur_score:.1f})"
        return face

    # Yaw angle from eye landmarks
    if face.landmarks is not None and len(face.landmarks) >= 2:
        eye_l, eye_r = face.landmarks[0], face.landmarks[1]
        eye_dist     = abs(float(eye_r[0]) - float(eye_l[0]))
        yaw_est      = (1.0 - eye_dist / max(float(w), 1.0)) * 90.0
        if yaw_est > cfg.max_yaw_degrees:
            face.quality_ok    = False
            face.reject_reason = f"extreme_yaw ({yaw_est:.0f}°)"
            return face

    face.quality_ok = True
    return face


# ── Step 3: Image Enhancement ──────────────────────────────────

def enhance_low_light(crop: np.ndarray) -> np.ndarray:
    """CLAHE on L-channel + gamma correction for dark gate cameras."""
    if crop.size == 0:
        return crop
    lab      = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
    l, a, b  = cv2.split(lab)
    clahe    = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l_eq     = clahe.apply(l)
    enhanced = cv2.cvtColor(cv2.merge((l_eq, a, b)), cv2.COLOR_LAB2BGR)
    lut      = np.array(
        [min(255, int(((i / 255.0) ** (1.0 / 1.4)) * 255)) for i in range(256)],
        dtype=np.uint8,
    )
    return cv2.LUT(enhanced, lut)


# ── Step 4: Anti-Spoofing ──────────────────────────────────────

def check_liveness(crop: np.ndarray) -> tuple[bool, float]:
    """
    Passive liveness check using texture analysis.
    Returns (is_spoof, spoof_score).
    """
    if crop.size == 0:
        return False, 0.0
    gray        = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    lap_var     = cv2.Laplacian(gray, cv2.CV_64F).var()
    spoof_score = max(0.0, 1.0 - min(lap_var / 500.0, 1.0))
    return spoof_score > 0.85, round(spoof_score, 4)


# ── Step 5: Employee Matching ──────────────────────────────────

def match_employee(
    query_emb:  np.ndarray,
    embeddings: dict[int, tuple[str, str, np.ndarray]],
) -> tuple[Optional[int], Optional[str], Optional[str], float]:
    """
    Cosine similarity search against enrolled employee embeddings.
    Returns (employee_id, name, code, similarity).
    """
    if not embeddings or query_emb is None:
        return None, None, None, 0.0

    q_norm = query_emb / (np.linalg.norm(query_emb) + 1e-8)
    best_id, best_name, best_code, best_sim = None, None, None, -1.0

    for eid, (name, code, db_emb) in embeddings.items():
        d_norm = db_emb / (np.linalg.norm(db_emb) + 1e-8)
        sim    = float(np.dot(q_norm, d_norm))
        if sim > best_sim:
            best_sim, best_id, best_name, best_code = sim, eid, name, code

    return best_id, best_name, best_code, round(best_sim, 4)


# ── Step 6: Annotate Frame ─────────────────────────────────────

def annotate_frame(
    frame:   np.ndarray,
    results: list[RecognitionResult],
) -> np.ndarray:
    """Draw bounding boxes + labels on frame."""
    out = frame.copy()
    for r in results:
        x1, y1, x2, y2 = r.face.bbox
        if r.is_spoof:
            color = (0, 165, 255)
            label = "SPOOF DETECTED"
        elif r.is_match:
            color = (0, 220, 80)
            label = f"{r.employee_name}  {r.similarity:.2f}"
        else:
            color = (0, 0, 230)
            label = f"Unknown  {r.similarity:.2f}"

        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(out, (x1, y1 - th - 10), (x1 + tw + 6, y1), color, -1)
        cv2.putText(
            out, label, (x1 + 3, y1 - 5),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA,
        )
        bar_w = int((x2 - x1) * max(r.similarity, 0))
        cv2.rectangle(out, (x1, y2 + 2), (x1 + bar_w, y2 + 5), color, -1)
    return out


# ── Main pipeline ──────────────────────────────────────────────

def process_frame(
    frame:      np.ndarray,
    embeddings: dict[int, tuple[str, str, np.ndarray]],
    camera_id:  int,
    gate_type:  str,
) -> tuple[list[RecognitionResult], np.ndarray]:
    """
    Full pipeline for one BGR video frame.
    Returns (results, annotated_frame).

    Agar model ready nahi hai → empty results, original frame.
    KOI FAKE DATA NAHI.
    """
    # Model ready nahi → kuch nahi karo
    if not is_model_ready():
        return [], frame.copy()

    t0      = time.perf_counter()
    results: list[RecognitionResult] = []

    detected = detect_faces(frame)

    for face in detected:
        face = filter_quality(face, frame)
        if not face.quality_ok:
            continue

        x1, y1, x2, y2 = face.bbox
        crop = frame[max(y1, 0):y2, max(x1, 0):x2]
        crop = enhance_low_light(crop)

        is_spoof, spoof_score = check_liveness(crop)

        eid, ename, ecode, sim = match_employee(face.embedding, embeddings)
        is_match = (
            sim >= cfg.similarity_threshold
            and not is_spoof
            and eid is not None
        )

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        results.append(RecognitionResult(
            employee_id=eid,
            employee_name=ename,
            employee_code=ecode,
            similarity=sim,
            is_match=is_match,
            face=face,
            is_spoof=is_spoof,
            spoof_score=spoof_score,
            proc_ms=round(elapsed_ms, 1),
        ))

    annotated = annotate_frame(frame, results)
    return results, annotated
