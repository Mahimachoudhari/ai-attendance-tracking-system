import sys, os, cv2, numpy as np
sys.path.insert(0, '.')
import psycopg2
from insightface.app import FaceAnalysis

conn = psycopg2.connect(
    host='localhost', dbname='attendance_db',
    user='postgres', password='Mahima@123'
)

print("Loading model...")
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=-1, det_size=(640, 640))
print("Model ready!")

image_folder = r'data\faces\image'
ok = 0
fail = 0

for emp_id in sorted(os.listdir(image_folder)):
    folder = os.path.join(image_folder, emp_id)
    if not os.path.isdir(folder):
        continue
    photos = [f for f in os.listdir(folder) if f.lower().endswith('.jpg')]
    embeddings = []
    for photo in photos:
        img = cv2.imread(os.path.join(folder, photo))
        if img is None:
            continue
        faces = app.get(img)
        if faces:
            emb = faces[0].embedding.astype(np.float32)
            emb = emb / (np.linalg.norm(emb) + 1e-8)
            embeddings.append(emb)
    if not embeddings:
        fail += 1
        continue
    avg = np.mean(embeddings, axis=0)
    avg = avg / (np.linalg.norm(avg) + 1e-8)
    cur = conn.cursor()
    cur.execute(
        'UPDATE employees SET face_embedding = %s WHERE employee_code = %s',
        (avg.tolist(), f'EMP{int(emp_id):04d}')
    )
    conn.commit()
    cur.close()
    ok += 1
    print(f'  OK  emp_id={emp_id}  ({len(embeddings)}/{len(photos)} photos)')

conn.close()
print(f'\nDone! {ok} enrolled, {fail} failed')