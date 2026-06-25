"""
demo/enroll_from_photos.py
---------------------------
Real employee photos se batch enrollment.

Photo file naming format (2 options):

  OPTION 1 — Simple:
    ACME0001_Aarav_Sharma.jpg

  OPTION 2 — With department & role (recommended):
    ACME0001_Aarav_Sharma_Engineering_Senior_Engineer.jpg

  Format: {CODE}_{Name}_{Department}_{Role}.jpg
  (Department aur Role optional hain)

Usage:
  # Backend ke saath (recommended):
  python demo/enroll_from_photos.py --photos-dir demo/photos

  # Direct DB (backend band ho):
  python demo/enroll_from_photos.py --photos-dir demo/photos --local
"""

from __future__ import annotations

import argparse
import os
import sys

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _parse_filename(fname: str) -> dict:
    """
    Parse employee info from filename.

    Examples:
      ACME0001_Aarav_Sharma.jpg
        → code=ACME0001, name=Aarav Sharma, dept=None, role=None

      ACME0001_Aarav_Sharma_Engineering_Senior_Engineer.jpg
        → code=ACME0001, name=Aarav Sharma, dept=Engineering, role=Senior Engineer
    """
    stem  = os.path.splitext(fname)[0]
    parts = stem.split("_")

    if len(parts) < 2:
        return {}

    code = parts[0].upper()

    # First name is always 2 words (First + Last)
    # Remaining parts are department + role
    if len(parts) == 2:
        # ACME0001_AaravSharma — single word name
        name = parts[1].replace("-", " ")
        dept = None
        role = None
    elif len(parts) == 3:
        # ACME0001_Aarav_Sharma
        name = f"{parts[1]} {parts[2]}"
        dept = None
        role = None
    elif len(parts) == 4:
        # ACME0001_Aarav_Sharma_Engineering
        name = f"{parts[1]} {parts[2]}"
        dept = parts[3]
        role = None
    elif len(parts) >= 5:
        # ACME0001_Aarav_Sharma_Engineering_Senior_Engineer
        name = f"{parts[1]} {parts[2]}"
        dept = parts[3]
        role = " ".join(parts[4:])
    else:
        return {}

    return {
        "code": code,
        "name": name.title(),
        "department": dept,
        "role": role,
    }


# ── Local enrollment (direct DB, no HTTP) ─────────────────────────────────────

def enroll_local(photos_dir: str) -> None:
    from backend.core.ai_pipeline import detect_faces, filter_quality, enhance_low_light
    from backend.services import database as db
    from backend.core import embedding_store
    from backend.config import cfg

    print("Initialising DB connection…")
    db.init_pool()
    embedding_store.load()
    print(f"DB ready. Starting enrollment from: {photos_dir}\n")

    counts = {"ok": 0, "fail": 0, "skip": 0}

    for fname in sorted(os.listdir(photos_dir)):
        if not fname.lower().endswith((".jpg", ".jpeg", ".png")):
            continue

        info = _parse_filename(fname)
        if not info:
            print(f"  SKIP  {fname}  ← filename format galat hai")
            counts["skip"] += 1
            continue

        path  = os.path.join(photos_dir, fname)
        frame = cv2.imread(path)
        if frame is None:
            print(f"  FAIL  {fname}  ← image read nahi hua")
            counts["fail"] += 1
            continue

        # Face detect karo
        faces = detect_faces(frame)
        if not faces:
            print(f"  FAIL  {fname}  ← koi face detect nahi hua — seedhi, clear photo use karo")
            counts["fail"] += 1
            continue

        # Best face pick karo
        face = max(faces, key=lambda f: f.det_confidence)
        face = filter_quality(face, frame)

        if not face.quality_ok:
            print(f"  FAIL  {fname}  ← quality check fail: {face.reject_reason}")
            counts["fail"] += 1
            continue

        if face.embedding is None:
            print(f"  FAIL  {fname}  ← embedding extract nahi hua")
            counts["fail"] += 1
            continue

        # DB mein save karo
        try:
            emp_id = db.create_employee(
                employee_code=info["code"],
                name=info["name"],
                company_id=cfg.company_id,
                department=info["department"],
                role=info["role"],
            )
            db.upsert_employee_embedding(emp_id, face.embedding.tolist())
            embedding_store.add(emp_id, info["name"], info["code"], face.embedding)

            dept_str = f"  [{info['department']}]" if info["department"] else ""
            print(
                f"  OK    {fname}\n"
                f"        → {info['name']} ({info['code']}){dept_str}"
                f"  id={emp_id}  confidence={face.det_confidence:.3f}"
            )
            counts["ok"] += 1

        except Exception as e:
            print(f"  FAIL  {fname}  ← DB error: {e}")
            counts["fail"] += 1

    print(f"\n{'='*50}")
    print(f"  Enrollment complete!")
    print(f"  ✅  Enrolled : {counts['ok']}")
    print(f"  ❌  Failed   : {counts['fail']}")
    print(f"  ⏭  Skipped  : {counts['skip']}")
    print(f"{'='*50}")
    if counts["ok"] > 0:
        print(f"\n  Ab backend start karo aur camera connect karo:")
        print(f"  uvicorn backend.main:app --port 8000")


# ── HTTP enrollment (backend running hona chahiye) ────────────────────────────

def enroll_http(photos_dir: str, server: str) -> None:
    try:
        import httpx
    except ImportError:
        print("httpx install karo: pip install httpx")
        sys.exit(1)

    base   = server.rstrip("/")
    counts = {"ok": 0, "fail": 0, "skip": 0}

    print(f"Backend: {base}")
    print(f"Photos:  {photos_dir}\n")

    for fname in sorted(os.listdir(photos_dir)):
        if not fname.lower().endswith((".jpg", ".jpeg", ".png")):
            continue

        info = _parse_filename(fname)
        if not info:
            print(f"  SKIP  {fname}  ← filename format galat hai")
            counts["skip"] += 1
            continue

        path = os.path.join(photos_dir, fname)
        ctype = "image/jpeg" if fname.lower().endswith((".jpg", ".jpeg")) else "image/png"

        with open(path, "rb") as fh:
            try:
                resp = httpx.post(
                    f"{base}/api/employees/enroll",
                    data={
                        "employee_code": info["code"],
                        "name":          info["name"],
                        "department":    info["department"] or "",
                        "role":          info["role"]       or "",
                    },
                    files={"photo": (fname, fh, ctype)},
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    dept_str = f"  [{info['department']}]" if info["department"] else ""
                    print(
                        f"  OK    {fname}\n"
                        f"        → {info['name']} ({info['code']}){dept_str}"
                        f"  id={data.get('employee_id')}  conf={data.get('confidence')}"
                    )
                    counts["ok"] += 1
                else:
                    print(f"  FAIL  {fname}  ← HTTP {resp.status_code}: {resp.text[:100]}")
                    counts["fail"] += 1
            except Exception as e:
                print(f"  FAIL  {fname}  ← {e}")
                counts["fail"] += 1

    print(f"\n{'='*50}")
    print(f"  Enrollment complete!")
    print(f"  ✅  Enrolled : {counts['ok']}")
    print(f"  ❌  Failed   : {counts['fail']}")
    print(f"  ⏭  Skipped  : {counts['skip']}")
    print(f"{'='*50}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Employee photos se batch enrollment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # HTTP mode (backend running):
  python demo/enroll_from_photos.py --photos-dir demo/photos

  # Local mode (direct DB):
  python demo/enroll_from_photos.py --photos-dir demo/photos --local

Photo naming:
  ACME0001_Aarav_Sharma.jpg
  ACME0001_Aarav_Sharma_Engineering_Senior_Engineer.jpg
        """
    )
    parser.add_argument("--photos-dir", required=True,
                        help="Photos folder ka path")
    parser.add_argument("--server",     default="http://localhost:8000",
                        help="Backend URL (HTTP mode ke liye)")
    parser.add_argument("--local",      action="store_true",
                        help="Direct DB use karo (backend band ho tab)")
    args = parser.parse_args()

    if not os.path.isdir(args.photos_dir):
        print(f"ERROR: Folder nahi mila: {args.photos_dir}")
        sys.exit(1)

    if args.local:
        enroll_local(args.photos_dir)
    else:
        enroll_http(args.photos_dir, args.server)