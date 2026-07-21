from __future__ import annotations
import os, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from backend.config import cfg
from backend.core import embedding_store
from backend.services import database as db
from backend.services import kafka_producer as kp

from backend.api.attendance import router as attendance_router
from backend.api.employees  import router as employees_router
from backend.api.alerts     import router as alerts_router
from backend.api.camera     import router as camera_router

_start_time  = time.monotonic()
_STATIC_DIR  = os.path.join(os.path.dirname(__file__), "..", "frontend", "static")
_DASHBOARD   = os.path.join(os.path.dirname(__file__), "..", "frontend", "templates", "dashboard.html")
_FAVICON_ICO = os.path.join(_STATIC_DIR, "favicon.ico")
_FAVICON_SVG = os.path.join(_STATIC_DIR, "favicon.svg")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("  AI Attendance System — starting up")
    logger.info("=" * 60)
    try:
        db.init_pool()
        if db.ping():
            logger.info("DB pool ready")
        else:
            logger.warning("DB pool initialized but ping failed; database features will be unavailable")
    except Exception as e:
        logger.warning(f"DB pool failed: {e}")
    logger.info("Loading AI model at startup...")
    try:
        from backend.core.ai_pipeline import _load_model, is_model_ready
        _load_model()
        if is_model_ready():
            logger.info("InsightFace model ready")
        else:
            logger.warning("InsightFace model not ready; AI recognition will be unavailable")
    except Exception as e:
        logger.error(f"Model load error: {e}")
    n = embedding_store.load()
    logger.info(f"Embeddings: {n} employees loaded")
    yield
    kp.close()
    db.close_pool()

app = FastAPI(title="AI Attendance System", version="1.0.0", lifespan=lifespan, docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(attendance_router)
app.include_router(employees_router)
app.include_router(alerts_router)
app.include_router(camera_router)

if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    if os.path.exists(_FAVICON_ICO):
        return FileResponse(_FAVICON_ICO, media_type="image/x-icon")
    from fastapi.responses import Response
    return Response(status_code=204)

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def serve_dashboard():
    if os.path.exists(_DASHBOARD):
        return HTMLResponse(content=open(_DASHBOARD, encoding="utf-8").read())
    return HTMLResponse("<h2>Dashboard not found</h2>", status_code=404)

@app.get("/api/health", tags=["System"])
async def health():
    from backend.core.ai_pipeline import is_model_ready
    try:
        db_connected = db.ping()
    except Exception:
        db_connected = False
    return {
        "status": "ok",
        "model_ready": is_model_ready(),
        "employees_cached": embedding_store.count(),
        "db_connected": db_connected,
        "uptime_seconds": round(time.monotonic() - _start_time, 1),
    }

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {exc}")
    return JSONResponse(status_code=500, content={"detail": str(exc)})