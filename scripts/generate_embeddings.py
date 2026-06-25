import os
import json
import cv2
import psycopg2

from insightface.app import FaceAnalysis

# -------------------------------
# InsightFace Model
# -------------------------------

app = FaceAnalysis(
    name="buffalo_l",
    providers=["CPUExecutionProvider"]
)

app.prepare(ctx_id=0)

# -------------------------------
# PostgreSQL Connection
# -------------------------------

conn = psycopg2.connect(
    host="localhost",
    database="attendance_db",
    user="postgres",
    password="Mahima@123"
)

cur = conn.cursor()

# -------------------------------
# Load Employees
# -------------------------------

cur.execute("""
SELECT id,name,face_image_path
FROM employees
WHERE face_image_path IS NOT NULL
""")

employees = cur.fetchall()

print(f"\nEmployees Found = {len(employees)}\n")

success = 0
failed = 0

# -------------------------------
# Generate Embeddings
# -------------------------------

for emp_id, name, folder in employees:

    try:

        if not os.path.exists(folder):
            print(f"Folder Missing: {name}")
            failed += 1
            continue

        image_path = None

        for file in os.listdir(folder):

            if file.lower().endswith(
                (".jpg", ".jpeg", ".png")
            ):
                image_path = os.path.join(folder, file)
                break

        if image_path is None:
            print(f"No Image: {name}")
            failed += 1
            continue

        img = cv2.imread(image_path)

        if img is None:
            print(f"Cannot Read: {name}")
            failed += 1
            continue

        faces = app.get(img)

        if len(faces) == 0:
            print(f"No Face Found: {name}")
            failed += 1
            continue

        embedding = faces[0].embedding.tolist()

        cur.execute("""
        UPDATE employees
        SET face_embedding = %s
        WHERE id = %s
        """,
        (
            json.dumps(embedding),
            emp_id
        ))

        success += 1

        print(
            f"[{success}] Embedded: {name}"
        )

    except Exception as e:

        failed += 1

        print(
            f"Error {name}: {e}"
        )

# -------------------------------
# Commit
# -------------------------------

conn.commit()

print("\n======================")
print(f"SUCCESS = {success}")
print(f"FAILED  = {failed}")
print("======================")

cur.close()
conn.close()