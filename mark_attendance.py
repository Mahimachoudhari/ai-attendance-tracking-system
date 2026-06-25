import sys, os, cv2, numpy as np
sys.path.insert(0, '.')
import psycopg2
from insightface.app import FaceAnalysis
from datetime import datetime

# DB connect
conn = psycopg2.connect(
    host='localhost', dbname='attendance_db',
    user='postgres', password='Mahima@123'
)

# Model load
print("Loading model...")
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=-1, det_size=(640,640))
print("Model ready!\n")

# DB se saare embeddings lo
cur = conn.cursor()
cur.execute("SELECT id, employee_code, name, face_embedding FROM employees WHERE face_embedding IS NOT NULL")
rows = cur.fetchall()
cur.close()

employees = []
for row in rows:
    emb = np.array(row[3], dtype=np.float32)
    emb = emb / (np.linalg.norm(emb) + 1e-8)
    employees.append({
        'id': row[0],
        'code': row[1],
        'name': row[2],
        'embedding': emb
    })

print(f"{len(employees)} employees loaded\n")

def match_face(query_emb):
    """Face embedding se employee dhundo"""
    query_emb = query_emb / (np.linalg.norm(query_emb) + 1e-8)
    best_sim = -1
    best_emp = None
    for emp in employees:
        sim = float(np.dot(query_emb, emp['embedding']))
        if sim > best_sim:
            best_sim = sim
            best_emp = emp
    return best_emp, best_sim

def mark_attendance(employee_id, employee_name, event_type='entry'):
    """DB mein attendance mark karo"""
    cur = conn.cursor()
    now = datetime.now()
    today = now.date()
    
    # Event log
    cur.execute("""
        INSERT INTO attendance_events 
            (employee_id, employee_name, company_id, camera_id, event_type, timestamp, confidence_score)
        VALUES (%s, %s, 1, 1, %s, %s, 1.0)
    """, (employee_id, employee_name, event_type, now))
    
    # Attendance record
    if event_type == 'entry':
        cur.execute("""
            INSERT INTO attendance (employee_id, employee_name, company_id, date, entry_time, status)
            VALUES (%s, %s, 1, %s, %s, 'present')
            ON CONFLICT (employee_id, date) DO NOTHING
        """, (employee_id, employee_name, today, now))
    else:
        cur.execute("""
            UPDATE attendance SET exit_time = %s 
            WHERE employee_id = %s AND date = %s
        """, (now, employee_id, today))
    
    conn.commit()
    cur.close()

# Photos se attendance mark karo
image_folder = r'data\faces\image'
SIMILARITY_THRESHOLD = 0.4

print("="*55)
print("  Photos se Attendance Mark ho rahi hai...")
print("="*55)

marked = 0
not_matched = 0

for emp_id in sorted(os.listdir(image_folder)):
    folder = os.path.join(image_folder, emp_id)
    if not os.path.isdir(folder):
        continue
    
    photos = [f for f in os.listdir(folder) if f.lower().endswith('.jpg')]
    if not photos:
        continue
    
    # Pehli photo use karo
    photo_path = os.path.join(folder, photos[0])
    img = cv2.imread(photo_path)
    if img is None:
        continue
    
    faces = app.get(img)
    if not faces:
        not_matched += 1
        continue
    
    emb = faces[0].embedding.astype(np.float32)
    matched_emp, similarity = match_face(emb)
    
    if similarity >= SIMILARITY_THRESHOLD and matched_emp:
        mark_attendance(matched_emp['id'], matched_emp['name'], 'entry')
        print(f"  ✅ ENTRY: {matched_emp['name']:<30} ({matched_emp['code']})  sim={similarity:.2%}")
        marked += 1
    else:
        not_matched += 1

conn.close()
print(f"\n{'='*55}")
print(f"  ✅ Attendance marked : {marked}")
print(f"  ❌ Not matched       : {not_matched}")
print(f"{'='*55}")
print("\nDashboard refresh karo: http://localhost:8000")