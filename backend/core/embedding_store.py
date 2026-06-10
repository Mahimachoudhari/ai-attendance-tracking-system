"""
backend/core/embedding_store.py
---------------------------------
Singleton embedding store that:
  • Loads all active employee embeddings from PostgreSQL on startup.
  • Pushes them into Redis for fast cross-process lookup.
  • Exposes get() for the AI pipeline (pure in-RAM, < 1 µs per call).
  • Supports hot-reload via reload() called after new enrollment.
"""

from __future__ import annotations

import threading

import numpy as np
from loguru import logger

from backend.config import cfg

# {employee_id: (name, employee_code, np.ndarray[128])}
_store: dict[int, tuple[str, str, np.ndarray]] = {}
_lock  = threading.RLock()


def load() -> int:
    """
    Pull embeddings from DB → populate in-process store → push to Redis.
    Returns number of employees loaded.
    Safe to call multiple times (idempotent).
    """
    from backend.services.database import get_employee_embeddings
    from backend.services.cache    import load_embeddings

    try:
        data = get_employee_embeddings(cfg.company_id)
    except Exception as e:
        logger.error(f"EmbeddingStore.load failed (DB unavailable?): {e}")
        return 0

    with _lock:
        _store.clear()
        _store.update(data)

    try:
        load_embeddings(data)
    except Exception as e:
        logger.warning(f"Redis push failed (non-fatal): {e}")

    n = len(_store)
    logger.info(f"EmbeddingStore loaded {n} embeddings (company_id={cfg.company_id})")
    return n


def reload() -> int:
    """Alias for load() — call after enrolling a new employee."""
    return load()


def get() -> dict[int, tuple[str, str, np.ndarray]]:
    """Return a shallow copy of the store (thread-safe, zero-copy on ndarray)."""
    with _lock:
        return dict(_store)


def add(employee_id: int, name: str, code: str, emb: np.ndarray) -> None:
    """Insert/update a single entry without a full reload."""
    with _lock:
        _store[employee_id] = (name, code, emb)

    from backend.services.cache import add_embedding
    try:
        add_embedding(employee_id, name, code, emb)
    except Exception:
        pass


def count() -> int:
    with _lock:
        return len(_store)