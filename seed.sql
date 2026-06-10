"""
database/seed_employees.py
---------------------------
Seeds 50 employees with realistic data and random normalised face embeddings.

In PRODUCTION:
  Replace random embeddings with real ArcFace embeddings by running:
    python demo/enroll_from_photos.py --photos-dir /path/to/employee/photos

Usage:
  python -m database.seed_employees
  -- or --
  cd attendance-system && python database/seed_employees.py
"""

from __future__ import annotations

import os
import sys
import random
import numpy as np

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import psycopg2
from backend.config import cfg

# ── Data ──────────────────────────────────────────────────────────────────────

EMPLOYEES = [
    # (name, department, role)
    ("Aarav Sharma",        "Engineering",   "Senior Engineer"),
    ("Priya Patel",         "HR",            "HR Manager"),
    ("Rohan Mehta",         "Operations",    "Operations Lead"),
    ("Ananya Singh",        "Finance",       "Finance Analyst"),
    ("Vikram Joshi",        "Engineering",   "DevOps Engineer"),
    ("Neha Gupta",          "HR",            "Recruiter"),
    ("Arjun Verma",         "Engineering",   "Backend Engineer"),
    ("Pooja Nair",          "Marketing",     "Marketing Executive"),
    ("Karan Malhotra",      "Security",      "Security Supervisor"),
    ("Divya Rao",           "Operations",    "Operations Analyst"),
    ("Siddharth Kumar",     "Engineering",   "Frontend Engineer"),
    ("Kavya Reddy",         "Finance",       "Senior Accountant"),
    ("Aditya Iyer",         "Engineering",   "ML Engineer"),
    ("Shreya Pillai",       "HR",            "HR Executive"),
    ("Rahul Das",           "Logistics",     "Logistics Manager"),
    ("Ishaan Chopra",       "Engineering",   "DevOps Engineer"),
    ("Meera Menon",         "Finance",       "Finance Manager"),
    ("Varun Bhatt",         "Operations",    "Production Supervisor"),
    ("Riya Kapoor",         "Marketing",     "Brand Manager"),
    ("Akash Tiwari",        "Engineering",   "QA Engineer"),
    ("Nisha Agarwal",       "HR",            "Payroll Executive"),
    ("Manish Bansal",       "Engineering",   "Embedded Engineer"),
    ("Sunita Pandey",       "Administration","Admin Manager"),
    ("Deepak Mishra",       "Security",      "Security Guard"),
    ("Anjali Dubey",        "Operations",    "Shift Supervisor"),
    ("Rajesh Yadav",        "Logistics",     "Fleet Manager"),
    ("Swati Jain",          "Finance",       "Junior Accountant"),
    ("Mohit Saxena",        "Engineering",   "Data Engineer"),
    ("Prachi Srivastava",   "Marketing",     "Content Strategist"),
    ("Abhishek Khanna",     "Engineering",   "Cloud Architect"),
    ("Tanvi Desai",         "HR",            "L&D Specialist"),
    ("Gaurav Bose",         "Engineering",   "Network Engineer"),
    ("Shreya Ghosh",        "Operations",    "Quality Inspector"),
    ("Nikhil Chatterjee",   "Engineering",   "Senior Engineer"),
    ("Pallavi Sen",         "Finance",       "Tax Consultant"),
    ("Harsh Mukherjee",     "Security",      "CCTV Operator"),
    ("Ruchi Bhatia",        "Administration","Office Coordinator"),
    ("Shubham Arora",       "Engineering",   "Python Developer"),
    ("Komal Thakur",        "Marketing",     "Digital Marketer"),
    ("Amit Choudhary",      "Logistics",     "Warehouse Manager"),
    ("Vandana Rajput",      "HR",            "HR Business Partner"),
    ("Sachin Rawat",        "Engineering",   "IoT Engineer"),
    ("Preeti Chandra",      "Finance",       "Budget Analyst"),
    ("Alok Shukla",         "Operations",    "Process Engineer"),
    ("Nandini Sinha",       "Engineering",   "AI Researcher"),
    ("Vivek Tripathi",      "Security",      "Security Officer"),
    ("Sonali Garg",         "Marketing",     "PR Executive"),
    ("Tarun Luthra",        "Engineering",   "Full Stack Developer"),
    ("Megha Sethi",         "Administration","Executive Assistant"),
    ("Hitesh Walia",        "Logistics",     "Supply Chain Analyst"),
]

SHIFT_OPTIONS = [
    ("08:00", "17:00"),
    ("08:30", "17:30"),
    ("09:00", "18:00"),
    ("09:30", "18:30"),
]


def random_unit_embedding(dim: int = 128, seed: int | None = None) -> list[float]:
    """Generate a unit-normalised random embedding (mimics ArcFace output)."""
    rng = np.random.default_rng(seed)
    v   = rng.standard_normal(dim).astype(np.float32)
    v  /= np.linalg.norm(v) + 1e-8
    return v.tolist()


def seed() -> None:
    print(f"Connecting to DB: {cfg.db_host}:{cfg.db_port}/{cfg.db_name} …")
    conn = psycopg2.connect(
        host=cfg.db_host, port=cfg.db_port,
        dbname=cfg.db_name, user=cfg.db_user, password=cfg.db_password,
    )
    cur  = conn.cursor()

    # Ensure company exists
    cur.execute(
        "INSERT INTO companies (code, name) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING",
        (cfg.company_code, "ACME Industries Ltd."),
    )

    inserted = 0
    skipped  = 0

    for i, (name, dept, role) in enumerate(EMPLOYEES, start=1):
        emp_code   = f"ACME{i:04d}"
        shift      = random.choice(SHIFT_OPTIONS)
        embedding  = random_unit_embedding(seed=i * 7)    # deterministic per employee

        cur.execute(
            """
            INSERT INTO employees
                (employee_code, name, company_id, department, role,
                 face_embedding, shift_start, shift_end, is_active)
            VALUES (%s, %s, 1, %s, %s, %s::vector, %s, %s, TRUE)
            ON CONFLICT (employee_code) DO NOTHING
            """,
            (emp_code, name, dept, role, embedding, shift[0], shift[1]),
        )
        if cur.rowcount:
            inserted += 1
        else:
            skipped += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"✅  Seed complete: {inserted} inserted, {skipped} already existed")
    print(f"    Total employees for company_id=1: {inserted + skipped}")


if __name__ == "__main__":
    seed()