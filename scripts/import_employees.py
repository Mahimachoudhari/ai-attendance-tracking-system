import os
import pandas as pd
import psycopg2

conn = psycopg2.connect(
    host="localhost",
    database="attendance_db",
    user="postgres",
    password="Mahima@123"
)

cur = conn.cursor()

csv_path = r"C:\Users\mahim\Downloads\employees (1).csv"

images_root = r"C:\Users\mahim\Downloads\image\image"

df = pd.read_csv(csv_path)

for _, row in df.iterrows():

    emp_id = str(row["emp_id"])

    employee_folder = os.path.join(images_root, emp_id)

    cur.execute("""
        INSERT INTO employees
        (
            employee_code,
            name,
            company_id,
            department,
            role,
            face_image_path
        )
        VALUES
        (%s,%s,%s,%s,%s,%s)
    """,
    (
        f"EMP{int(row['emp_id']):04}",
        row["name"],
        1,
        row["department"],
        "Employee",
        employee_folder
    ))

conn.commit()

cur.close()
conn.close()

print("Employees Imported Successfully")