"""
demo/enroll_from_photos.py
---------------------------
Batch-enroll employees from a folder of face photos.

Expected folder structure:
  photos/
    ACME0001_Aarav_Sharma.jpg
    ACME0002_Priya_Patel.png
    ...

Filename format: {employee_code}_{Name_With_Underscores}.{ext}

Usage:
  python demo/enroll_from_photos.py --photos-dir demo/photos --server http://localhost:8000

Or using the local pipeline directly (no HTTP):
  python demo/enroll_from_photos.py --photos-dir demo/photos --local
"""

from __future__ import annotations

import argparse
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Local enrollment (direct DB + pipeline) ────────────────────────────────────

def enroll_local(photos_dir: str) -> None:
    from backend.core.ai_pipeline import detect_faces, filter_quality, enhance_low_light
    from backend.services import database as db
    from backend.core import embedding_store
    from backend.config import cfg

    db.init_pool()
    embedding_store.load()

    results = {"ok": 0, "fail": 0, "skip": 0}

    for fname in sorted(os.listdir(photos_dir)):
        if not fname.lower().endswith((".jpg", ".jpeg", ".png")):
            continue

        stem = os.path.splitext(fname)[0]
        parts = stem.split("_", 1)
        if len(parts) < 2:
            print(f"  SKIP {fname}  (expected CODE_Name format)")
            results["skip"] += 1
            continue

        emp_code = parts[0].upper()
        name     = parts[1].replace("_", " ").title()
        path     = os.path.join(photos_dir, fname)

        frame = cv2.imread(path)
        if frame is None:
            print(f"  FAIL {fname}  (cannot read image)")
            results["fail"] += 1
            continue

        faces = detect_faces(frame)
        if not faces:
            print(f"  FAIL {fname}  (no face detected)")
            results["fail"] += 1
            continue

        face = max(faces, key=lambda f: f.det_confidence)
        face = filter_quality(face, frame)
        if not face.quality_ok:
            print(f"  FAIL {fname}  (quality: {face.reject_reason})")
            results["fail"] += 1
            continue

        if face.embedding is None:
            print(f"  FAIL {fname}  (no embedding)")
            results["fail"] += 1
            continue

        emb = face.embedding

        try:
            emp_id = db.create_employee(
                employee_code=emp_code,
                name=name,
                company_id=cfg.company_id,
                department=None,
                role=None,
            )
            db.upsert_employee_embedding(emp_id, emb.tolist())
            embedding_store.add(emp_id, name, emp_code, emb)
            print(f"  OK   {fname}  → {name} ({emp_code}) id={emp_id}  conf={face.det_confidence:.3f}")
            results["ok"] += 1
        except Exception as e:
            print(f"  FAIL {fname}  (DB error: {e})")
            results["fail"] += 1

    print(f"\nDone: {results['ok']} enrolled, {results['fail']} failed, {results['skip']} skipped")


# ── HTTP enrollment (via /api/employees/enroll) ────────────────────────────────

def enroll_http(photos_dir: str, server: str) -> None:
    import httpx

    base = server.rstrip("/")
    results = {"ok": 0, "fail": 0, "skip": 0}

    for fname in sorted(os.listdir(photos_dir)):
        if not fname.lower().endswith((".jpg", ".jpeg", ".png")):
            continue

        stem  = os.path.splitext(fname)[0]
        parts = stem.split("_", 1)
        if len(parts) < 2:
            print(f"  SKIP {fname}")
            results["skip"] += 1
            continue

        emp_code = parts[0].upper()
        name     = parts[1].replace("_", " ").title()
        path     = os.path.join(photos_dir, fname)

        with open(path, "rb") as fh:
            content_type = "image/jpeg" if fname.lower().endswith((".jpg", ".jpeg")) else "image/png"
            try:
                resp = httpx.post(
                    f"{base}/api/employees/enroll",
                    data={"employee_code": emp_code, "name": name},
                    files={"photo": (fname, fh, content_type)},
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    print(f"  OK   {fname}  → id={data.get('employee_id')}  conf={data.get('confidence')}")
                    results["ok"] += 1
                else:
                    print(f"  FAIL {fname}  → HTTP {resp.status_code}: {resp.text[:120]}")
                    results["fail"] += 1
            except Exception as e:
                print(f"  FAIL {fname}  → {e}")
                results["fail"] += 1

    print(f"\nDone: {results['ok']} enrolled, {results['fail']} failed, {results['skip']} skipped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch enroll employees from photos")
    parser.add_argument("--photos-dir", required=True,               help="Folder containing face photos")
    parser.add_argument("--server",     default="http://localhost:8000", help="Backend URL (HTTP mode)")
    parser.add_argument("--local",      action="store_true",          help="Use local pipeline (no HTTP)")
    args = parser.parse_args()

    if not os.path.isdir(args.photos_dir):
        print(f"ERROR: photos-dir not found: {args.photos_dir}")
        sys.exit(1)

    print(f"Enrolling from: {args.photos_dir}")
    if args.local:
        enroll_local(args.photos_dir)
    else:
        enroll_http(args.photos_dir, args.server)