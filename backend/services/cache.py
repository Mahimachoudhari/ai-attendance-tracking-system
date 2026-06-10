"""
backend/services/cache.py
--------------------------
Redis-backed embedding cache.
• Loads all employee embeddings into RAM on startup.
• Falls back gracefully if Redis is unavailable (uses dict only).
• Thread-safe reads (embeddings are read-only after load).
"""

from __future__ import annotations

import json
import threading
from typing import Optional

import numpy as np
import redis as redis_lib
from loguru import logger

from backend.config import cfg

# ── In-process embedding store ─────────────────────────────────────────────────
# {employee_id: (name, employee_code, embedding_array)}
_embeddings: dict[int, tuple[str, str, np.ndarray]] = {}
_lock = threading.RLock()

# ── Redis client ───────────────────────────────────────────────────────────────
_redis: Optional[redis_lib.Redis] = None


def _get_redis() -> Optional[redis_lib.Redis]:
    global _redis
    if _redis is not None:
        return _redis
    try:
        r = redis_lib.Redis(
            host=cfg.redis_host,
            port=cfg.redis_port,
            db=cfg.redis_db,
            password=cfg.redis_password or None,
            socket_connect_timeout=2,
            decode_responses=True,
        )
        r.ping()
        _redis = r
        logger.info(f"Redis connected: {cfg.redis_host}:{cfg.redis_port}")
    except Exception as e:
        logger.warning(f"Redis unavailable ({e}), using in-process cache only")
        _redis = None
    return _redis


# ── Public API ─────────────────────────────────────────────────────────────────

def load_embeddings(data: dict[int, tuple[str, str, np.ndarray]]) -> None:
    """Bulk-load embeddings into the in-process store (and Redis if available)."""
    with _lock:
        _embeddings.clear()
        _embeddings.update(data)

    r = _get_redis()
    if r is None:
        return

    pipe = r.pipeline()
    for eid, (name, code, emb) in data.items():
        key = f"emb:{eid}"
        payload = json.dumps({
            "name": name,
            "code": code,
            "emb":  emb.tolist(),
        })
        pipe.setex(key, cfg.redis_embedding_ttl, payload)
    try:
        pipe.execute()
        logger.info(f"Pushed {len(data)} embeddings to Redis")
    except Exception as e:
        logger.warning(f"Redis pipeline error: {e}")


def get_embeddings() -> dict[int, tuple[str, str, np.ndarray]]:
    """Return a snapshot of the current in-process embedding store."""
    with _lock:
        return dict(_embeddings)


def add_embedding(employee_id: int, name: str, code: str, emb: np.ndarray) -> None:
    """Add or update a single embedding (after enrollment)."""
    with _lock:
        _embeddings[employee_id] = (name, code, emb)

    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(
            f"emb:{employee_id}",
            cfg.redis_embedding_ttl,
            json.dumps({"name": name, "code": code, "emb": emb.tolist()}),
        )
    except Exception as e:
        logger.warning(f"Redis set error: {e}")


def remove_embedding(employee_id: int) -> None:
    with _lock:
        _embeddings.pop(employee_id, None)
    r = _get_redis()
    if r:
        try:
            r.delete(f"emb:{employee_id}")
        except Exception:
            pass


def count() -> int:
    with _lock:
        return len(_embeddings)


def ping_redis() -> bool:
    r = _get_redis()
    if r is None:
        return False
    try:
        return r.ping()
    except Exception:
        return False