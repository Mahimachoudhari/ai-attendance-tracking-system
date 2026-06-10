"""
backend/models/schemas.py
--------------------------
Pydantic models for API request/response validation.
"""

from __future__ import annotations
from datetime import datetime, date, time
from typing import Optional, List
from pydantic import BaseModel, Field


# ── Employee ────────────────────────────────────────────────────────────────────

class EmployeeBase(BaseModel):
    employee_code: str
    name:          str
    department:    Optional[str] = None
    role:          Optional[str] = None
    shift_start:   Optional[time] = time(9, 0)
    shift_end:     Optional[time] = time(18, 0)


class EmployeeCreate(EmployeeBase):
    company_id: int = 1


class EmployeeOut(EmployeeBase):
    id:          int
    company_id:  int
    is_active:   bool
    enrolled_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Attendance ──────────────────────────────────────────────────────────────────

class AttendanceRecord(BaseModel):
    id:               int
    employee_id:      int
    employee_name:    str
    employee_code:    Optional[str] = None
    department:       Optional[str] = None
    date:             date
    entry_time:       Optional[datetime] = None
    exit_time:        Optional[datetime] = None
    work_duration:    Optional[str] = None          # formatted HH:MM:SS
    entry_confidence: Optional[float] = None
    exit_confidence:  Optional[float] = None
    status:           str = "present"

    class Config:
        from_attributes = True


class AttendanceSummary(BaseModel):
    date:       str
    present:    int = 0
    exited:     int = 0
    late:       int = 0
    absent:     int = 0
    avg_hours:  Optional[float] = None


class AttendanceTodayResponse(BaseModel):
    summary: AttendanceSummary
    records: List[AttendanceRecord]


# ── Events ──────────────────────────────────────────────────────────────────────

class AttendanceEvent(BaseModel):
    employee_id:    Optional[int]   = None
    employee_name:  Optional[str]   = None
    employee_code:  Optional[str]   = None
    camera_id:      int
    gate_type:      str             # entry | exit
    timestamp:      datetime
    confidence:     float
    track_id:       Optional[int]   = None
    is_spoof:       bool            = False
    proc_ms:        float           = 0.0


class LiveEventsResponse(BaseModel):
    events: List[AttendanceEvent]


# ── Security Alert ──────────────────────────────────────────────────────────────

class SecurityAlert(BaseModel):
    id:           int
    camera_id:    Optional[int]
    alert_type:   str
    timestamp:    datetime
    confidence:   Optional[float]
    is_resolved:  bool
    notes:        Optional[str]

    class Config:
        from_attributes = True


class SecurityAlertsResponse(BaseModel):
    alerts: List[SecurityAlert]


# ── WebSocket messages ─────────────────────────────────────────────────────────

class WsAttendanceEvent(BaseModel):
    type:           str = "attendance_event"
    gate:           str
    employee_name:  Optional[str]
    employee_code:  Optional[str]
    confidence:     float
    timestamp:      str
    is_spoof:       bool  = False
    proc_ms:        float = 0.0
    work_duration:  Optional[str] = None


class WsSecurityAlert(BaseModel):
    type:       str = "security_alert"
    alert:      str
    camera_id:  int
    timestamp:  str


class WsAnnotatedFrame(BaseModel):
    type:       str = "annotated_frame"
    data:       str           # base64 JPEG
    events:     list
    proc_ms:    float
    face_count: int


# ── Enrollment ─────────────────────────────────────────────────────────────────

class EnrollRequest(BaseModel):
    employee_code: str
    name:          str
    department:    Optional[str] = None
    role:          Optional[str] = None
    company_id:    int = 1


class EnrollResponse(BaseModel):
    success:     bool
    employee_id: Optional[int]
    message:     str


# ── Health ──────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status:            str
    employees_cached:  int
    db_connected:      bool
    redis_connected:   bool
    kafka_connected:   bool
    uptime_seconds:    float