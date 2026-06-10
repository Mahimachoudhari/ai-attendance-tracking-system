"""
backend/main.py
----------------
FastAPI application factory.

Startup sequence:
  1. Init DB connection pool
  2. Load employee embeddings into RAM + Redis
  3. Register all API routers
  4. Mount frontend static files + dashboard template

Run:
  uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from backend.config import cfg
from backend.core import embedding_store
from backend.services import database as db
from backend.services import kafka_producer as kp

# ── Routers ────────────────────────────────────────────────────────────────────
from backend.api.attendance import router as attendance_router
from backend.api.employees  import router as employees_router
from backend.api.alerts     import router as alerts_router
from backend.api.camera     import router as camera_router

# ── App start time (for uptime calculation) ────────────────────────────────────
_start_time = time.monotonic()


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ───────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("  AI Attendance System — starting up")
    logger.info(f"  ENV={cfg.app_env}  GPU={cfg.gpu_id}  Company={cfg.company_code}")
    logger.info("=" * 60)

    # Init DB pool
    try:
        db.init_pool()
        logger.info("✅  DB pool ready")
    except Exception as e:
        logger.warning(f"⚠️  DB pool failed (demo mode): {e}")

    # Load embeddings
    n = embedding_store.load()
    logger.info(f"✅  Embeddings: {n} employees loaded")

    yield

    # ── SHUTDOWN ──────────────────────────────────────────────────────────────
    logger.info("Shutting down…")
    kp.close()
    db.close_pool()
    logger.info("Shutdown complete")


# ── App factory ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Attendance System",
    description="Face recognition attendance & entry-exit tracking for 600+ employees",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — allow all origins in dev, restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if cfg.app_env == "development" else [f"http://{cfg.app_host}:{cfg.app_port}"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(attendance_router)
app.include_router(employees_router)
app.include_router(alerts_router)
app.include_router(camera_router)

# ── Static files ───────────────────────────────────────────────────────────────
_static_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# ── Dashboard HTML ─────────────────────────────────────────────────────────────
_dashboard_path = os.path.join(
    os.path.dirname(__file__), "..", "frontend", "templates", "dashboard.html"
)

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def serve_dashboard():
    if os.path.exists(_dashboard_path):
        return HTMLResponse(content=open(_dashboard_path, encoding="utf-8").read())
    return HTMLResponse("<h2>Dashboard template not found</h2>", status_code=404)


# ── Health check ───────────────────────────────────────────────────────────────

@app.get("/api/health", tags=["System"])
async def health():
    from backend.services.cache import ping_redis
    return {
        "status":           "ok",
        "employees_cached": embedding_store.count(),
        "db_connected":     db.ping(),
        "redis_connected":  ping_redis(),
        "kafka_connected":  kp.is_connected(),
        "uptime_seconds":   round(time.monotonic() - _start_time, 1),
        "env":              cfg.app_env,
        "company":          cfg.company_code,
        "gpu_id":           cfg.gpu_id,
    }


# ── Global exception handler ───────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)},
    )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=cfg.app_host,
        port=cfg.app_port,
        reload=(cfg.app_env == "development"),
        log_level="info",
    )