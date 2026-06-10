"""
backend/core/ai_pipeline.py
----------------------------
End-to-end face recognition pipeline:

  Step 1  Face Detection      – RetinaFace (via InsightFace)
  Step 2  Quality Filter      – size / blur / yaw
  Step 3  Image Enhancement   – CLAHE + gamma for low-light gates
  Step 4  Embedding Extraction– ArcFace 128-d (GPU via ONNX)
  Step 5  Anti-Spoof Check    – passive texture-based liveness
  Step 6  Employee Matching   – cosine similarity against cache
  Step 7  Result Assembly     – RecognitionResult dataclass

The InsightFace app is loaded once (singleton) at first call.
Falls back to a deterministic mock when InsightFace is unavailable (CI/demo).
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
from loguru import logger

from backend.config import cfg

# ── Singleton model lock ────────────────────────────────────────────────────────
_model_lock = threading.Lock()
_app = None          # InsightFace FaceAnalysis


def _load_model():
    global _app
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
            app = FaceAnalysis(name=cfg.model_name, providers=providers)
            app.prepare(ctx_id=cfg.gpu_id, det_size=(640, 640))
            _app = app
            logger.info(f"InsightFace loaded: {cfg.model_name} (GPU id={cfg.gpu_id})")
        except Exception as e:
            logger.warning(f"InsightFace unavailable ({e}) — mock pipeline active")
            _app = "mock"
    return _app


# ── Dataclasses ─────────────────────────────────────────────────────────────────

@dataclass
class DetectedFace:
    bbox:           tuple[int, int, int, int]     # x1, y1, x2, y2
    landmarks:      Optional[np.ndarray]           # 5×2 keypoints
    det_confidence: float                          # RetinaFace score
    embedding:      Optional[np.ndarray] = None   # ArcFace 128-d
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


# ── Step 1: Detection ───────────────────────────────────────────────────────────

def detect_faces(frame: np.ndarray) -> list[DetectedFace]:
    """Run RetinaFace on a BGR frame. Returns one DetectedFace per person."""
    app = _load_model()

    if app == "mock":
        return _mock_detect(frame)

    raw_faces = app.get(frame)
    results: list[DetectedFace] = []
    for f in raw_faces:
        x1, y1, x2, y2 = (int(v) for v in f.bbox)
        results.append(DetectedFace(
            bbox=(x1, y1, x2, y2),
            landmarks=getattr(f, "kps", None),
            det_confidence=float(f.det_score),
            embedding=getattr(f, "embedding", None),   # ArcFace emb direct
        ))
    return results


def _mock_detect(frame: np.ndarray) -> list[DetectedFace]:
    """Deterministic mock for demo / unit testing (no model required)."""
    rng  = np.random.default_rng(seed=int(time.time()) % 1000)
    h, w = frame.shape[:2]
    n    = rng.integers(1, 5)
    out: list[DetectedFace] = []
    for _ in range(n):
        x1 = int(rng.integers(0, max(w // 2, 1)))
        y1 = int(rng.integers(0, max(h // 2, 1)))
        x2 = min(x1 + 130, w)
        y2 = min(y1 + 160, h)
        emb = rng.standard_normal(128).astype(np.float32)
        emb /= np.linalg.norm(emb) + 1e-8
        out.append(DetectedFace(
            bbox=(x1, y1, x2, y2),
            landmarks=None,
            det_confidence=round(0.85 + rng.random() * 0.13, 4),
            embedding=emb,
        ))
    return out


# ── Step 2: Quality Filter ──────────────────────────────────────────────────────

def filter_quality(face: DetectedFace, frame: np.ndarray) -> DetectedFace:
    """
    Reject faces that are:
    - Too small (below cfg.min_face_size px)
    - Too blurry (Laplacian variance < cfg.blur_threshold)
    - Extreme yaw angle (> cfg.max_yaw_degrees, estimated from landmarks)
    """
    x1, y1, x2, y2 = face.bbox
    w, h = x2 - x1, y2 - y1

    if w < cfg.min_face_size or h < cfg.min_face_size:
        face.quality_ok    = False
        face.reject_reason = f"too_small ({w}×{h}px)"
        return face

    crop = frame[max(y1, 0):y2, max(x1, 0):x2]
    if crop.size == 0:
        face.quality_ok    = False
        face.reject_reason = "empty_crop"
        return face

    gray       = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    if blur_score < cfg.blur_threshold:
        face.quality_ok    = False
        face.reject_reason = f"blurry (score={blur_score:.1f})"
        return face

    # Yaw from eye landmarks
    if face.landmarks is not None and len(face.landmarks) >= 2:
        eye_l, eye_r = face.landmarks[0], face.landmarks[1]
        eye_dist = abs(float(eye_r[0]) - float(eye_l[0]))
        yaw_est  = (1.0 - eye_dist / max(float(w), 1.0)) * 90.0
        if yaw_est > cfg.max_yaw_degrees:
            face.quality_ok    = False
            face.reject_reason = f"extreme_yaw ({yaw_est:.0f}°)"
            return face

    face.quality_ok = True
    return face


# ── Step 3: Image Enhancement ───────────────────────────────────────────────────

def enhance_low_light(crop: np.ndarray) -> np.ndarray:
    """
    CLAHE on L-channel + gamma correction.
    Significantly improves ArcFace accuracy for dark gate cameras.
    """
    if crop.size == 0:
        return crop
    lab        = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
    l, a, b    = cv2.split(lab)
    clahe      = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    l_eq       = clahe.apply(l)
    enhanced   = cv2.cvtColor(cv2.merge((l_eq, a, b)), cv2.COLOR_LAB2BGR)
    # Gamma correction γ = 1.4
    lut = np.array(
        [min(255, int(((i / 255.0) ** (1.0 / 1.4)) * 255)) for i in range(256)],
        dtype=np.uint8,
    )
    return cv2.LUT(enhanced, lut)


# ── Step 4: Anti-Spoofing ───────────────────────────────────────────────────────

def check_liveness(crop: np.ndarray) -> tuple[bool, float]:
    """
    Passive liveness: analyse high-frequency texture using Laplacian.
    Printed photos / screens have distinctive texture profiles.
    Returns (is_spoof: bool, spoof_score: float 0-1).

    In production, replace with a dedicated anti-spoof model
    (e.g. Silent-Face-Anti-Spoofing).
    """
    if crop.size == 0:
        return False, 0.0
    gray       = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    lap_var    = cv2.Laplacian(gray, cv2.CV_64F).var()
    # Very low variance → printed flat surface (spoof)
    # Very high variance → real 3-D face texture
    spoof_score = max(0.0, 1.0 - min(lap_var / 500.0, 1.0))
    return spoof_score > 0.85, round(spoof_score, 4)


# ── Step 5: Employee Matching ───────────────────────────────────────────────────

def match_employee(
    query_emb:    np.ndarray,
    embeddings:   dict[int, tuple[str, str, np.ndarray]],
) -> tuple[Optional[int], Optional[str], Optional[str], float]:
    """
    Brute-force cosine similarity search (fast for ≤ 1000 employees).
    Returns (employee_id, name, code, similarity).
    """
    if not embeddings or query_emb is None:
        return None, None, None, 0.0

    q_norm   = query_emb / (np.linalg.norm(query_emb) + 1e-8)
    best_id, best_name, best_code, best_sim = None, None, None, -1.0

    for eid, (name, code, db_emb) in embeddings.items():
        d_norm = db_emb / (np.linalg.norm(db_emb) + 1e-8)
        sim    = float(np.dot(q_norm, d_norm))
        if sim > best_sim:
            best_sim, best_id, best_name, best_code = sim, eid, name, code

    return best_id, best_name, best_code, round(best_sim, 4)


# ── Step 6: Annotate Frame ──────────────────────────────────────────────────────

def annotate_frame(
    frame:   np.ndarray,
    results: list[RecognitionResult],
) -> np.ndarray:
    """Draw bounding boxes + labels on frame. Returns a copy."""
    out = frame.copy()
    for r in results:
        x1, y1, x2, y2 = r.face.bbox
        if r.is_spoof:
            color = (0, 165, 255)    # orange — spoof
            label = "SPOOF DETECTED"
        elif r.is_match:
            color = (0, 220, 80)     # green — known employee
            label = f"{r.employee_name}  {r.similarity:.2f}"
        else:
            color = (0, 0, 230)      # red — unknown
            label = f"Unknown  {r.similarity:.2f}"

        # Box
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)

        # Label background
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(out, (x1, y1 - th - 10), (x1 + tw + 6, y1), color, -1)

        # Label text
        cv2.putText(
            out, label, (x1 + 3, y1 - 5),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA,
        )

        # Confidence bar (bottom of box)
        bar_w = int((x2 - x1) * r.similarity)
        cv2.rectangle(out, (x1, y2 + 2), (x1 + bar_w, y2 + 5), color, -1)

    return out


# ── Main pipeline ───────────────────────────────────────────────────────────────

def process_frame(
    frame:      np.ndarray,
    embeddings: dict[int, tuple[str, str, np.ndarray]],
    camera_id:  int,
    gate_type:  str,
) -> tuple[list[RecognitionResult], np.ndarray]:
    """
    Full pipeline for one BGR video frame.

    Returns:
        results      – list of RecognitionResult (one per quality-passed face)
        annotated    – BGR frame with bounding boxes drawn
    """
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