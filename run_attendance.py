"""
run_attendance.py
-----------------
Seedha camera se attendance mark karta hai.
Backend ki zaroorat nahi - seedha DB mein save karta hai.
Dashboard API se data fetch karta hai.
"""

import cv2, numpy as np, psycopg2, time, sys
from datetime import datetime
from insightface.app import FaceAnalysis

# ── Config ─────────────────────────────────────────────────────
DB_CONFIG = dict(host='localhost', dbname='attendance_db',
                 user='postgres', password='Mahima@123')
VIDEO_SOURCE  = r'demo\test_entry.mp4'   # 0 = webcam, ya video path
GATE_TYPE     = 'entry'                   # 'entry' ya 'exit'
CAMERA_ID     = 1
MATCH_THRESHOLD = 0.35
COMPANY_ID    = 1

# ── Load Model ──────────────────────────────────────────────────
print("Model load ho raha hai...")
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=-1, det_size=(640, 640))
print("Model ready!\n")

# ── DB connect ──────────────────────────────────────────────────
conn = psycopg2.connect(**DB_CONFIG)
print("DB connected!")

# ── Saare employees ke embeddings lo ───────────────────────────
cur = conn.cursor()
cur.execute("SELECT id, employee_code, name, face_embedding FROM employees WHERE face_embedding IS NOT NULL")
rows = cur.fetchall()
cur.close()

employees = []
for r in rows:
    emb = np.array(r[3], dtype=np.float32)
    emb /= np.linalg.norm(emb) + 1e-8
    employees.append({'id': r[0], 'code': r[1], 'name': r[2], 'emb': emb})

print(f"{len(employees)} employees loaded\n")

# ── Already marked track karo (duplicate avoid) ─────────────────
marked_today = set()
cur = conn.cursor()
cur.execute("SELECT employee_id FROM attendance WHERE date = CURRENT_DATE AND entry_time IS NOT NULL")
for row in cur.fetchall():
    marked_today.add(row[0])
cur.close()
print(f"{len(marked_today)} already marked today\n")

# ── Face match ──────────────────────────────────────────────────
def match(query_emb):
    query_emb = query_emb / (np.linalg.norm(query_emb) + 1e-8)
    best, best_sim = None, -1
    for emp in employees:
        sim = float(np.dot(query_emb, emp['emb']))
        if sim > best_sim:
            best_sim, best = sim, emp
    return best, best_sim

# ── Attendance mark ─────────────────────────────────────────────
def mark_attendance(emp_id, emp_name, emp_code, sim):
    if emp_id in marked_today:
        return False
    now = datetime.now()
    cur = conn.cursor()
    # Event log
    cur.execute("""
        INSERT INTO attendance_events
            (employee_id, employee_name, company_id, camera_id, event_type, timestamp, confidence_score)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (emp_id, emp_name, COMPANY_ID, CAMERA_ID, GATE_TYPE, now, sim))
    # Attendance
    cur.execute("""
        INSERT INTO attendance (employee_id, employee_name, company_id, date, entry_time, status)
        VALUES (%s, %s, %s, CURRENT_DATE, %s, 'present')
        ON CONFLICT (employee_id, date) DO NOTHING
    """, (emp_id, emp_name, COMPANY_ID, now))
    conn.commit()
    cur.close()
    marked_today.add(emp_id)
    return True

# ── Video / Camera open ─────────────────────────────────────────
print(f"Camera/Video open kar raha hai: {VIDEO_SOURCE}")
cap = cv2.VideoCapture(VIDEO_SOURCE)

if not cap.isOpened():
    print(f"ERROR: {VIDEO_SOURCE} open nahi hua!")
    sys.exit(1)

print("Camera ready! Processing frames...\n")
print("="*55)

frame_count = 0
process_every = 5   # har 5th frame process karo

while True:
    ret, frame = cap.read()
    if not ret:
        # Video khatam - loop karo
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        continue

    frame_count += 1
    if frame_count % process_every != 0:
        continue

    # Face detect karo
    faces = app.get(frame)
    if not faces:
        continue

    for face in faces:
        if face.det_score < 0.5:
            continue
        if face.embedding is None:
            continue

        matched_emp, sim = match(face.embedding)

        if sim >= MATCH_THRESHOLD and matched_emp:
            success = mark_attendance(
                matched_emp['id'],
                matched_emp['name'],
                matched_emp['code'],
                sim
            )
            if success:
                ts = datetime.now().strftime('%H:%M:%S')
                print(f"  ENTRY: {matched_emp['name']:<30} ({matched_emp['code']})  {sim:.0%}  {ts}")

conn.release() if hasattr(conn, 'release') else None
cap.release()
conn.close()