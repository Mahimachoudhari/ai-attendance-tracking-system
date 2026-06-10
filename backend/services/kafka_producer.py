"""
backend/services/kafka_producer.py
------------------------------------
Async-safe Kafka producer wrapper.
Falls back gracefully when Kafka is not running (dev / demo mode).
All publishes are fire-and-forget (non-blocking).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any, Optional

from loguru import logger

from backend.config import cfg

_producer = None
_producer_lock = threading.Lock()
_kafka_available = False


def _get_producer():
    global _producer, _kafka_available
    if _producer is not None:
        return _producer
    with _producer_lock:
        if _producer is not None:
            return _producer
        try:
            from kafka import KafkaProducer
            _producer = KafkaProducer(
                bootstrap_servers=cfg.kafka_bootstrap_servers,
                value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
                acks="all",
                retries=3,
                linger_ms=5,
                request_timeout_ms=5000,
            )
            _kafka_available = True
            logger.info(f"Kafka producer connected: {cfg.kafka_bootstrap_servers}")
        except Exception as e:
            logger.warning(f"Kafka unavailable ({e}), events will not be published")
            _producer = "unavailable"
    return _producer


def publish_event(payload: dict[str, Any]) -> None:
    """Publish an attendance event to Kafka (non-blocking)."""
    p = _get_producer()
    if p == "unavailable" or p is None:
        return
    try:
        p.send(cfg.kafka_topic_events, value=payload)
    except Exception as e:
        logger.warning(f"Kafka publish error: {e}")


def publish_alert(payload: dict[str, Any]) -> None:
    """Publish a security alert to Kafka (non-blocking)."""
    p = _get_producer()
    if p == "unavailable" or p is None:
        return
    try:
        p.send(cfg.kafka_topic_alerts, value=payload)
    except Exception as e:
        logger.warning(f"Kafka alert publish error: {e}")


def build_event_payload(
    employee_id:   Optional[int],
    employee_name: Optional[str],
    employee_code: Optional[str],
    camera_id:     int,
    gate_type:     str,
    confidence:    float,
    timestamp:     datetime,
    track_id:      Optional[int] = None,
) -> dict:
    return {
        "employee_id":   employee_id,
        "employee_name": employee_name,
        "employee_code": employee_code,
        "camera_id":     camera_id,
        "gate_type":     gate_type,
        "confidence":    round(confidence, 4),
        "timestamp":     timestamp.isoformat(),
        "track_id":      track_id,
        "company_id":    cfg.company_id,
    }


def is_connected() -> bool:
    return _kafka_available


def close() -> None:
    global _producer
    if _producer and _producer != "unavailable":
        try:
            _producer.flush(timeout=5)
            _producer.close()
        except Exception:
            pass
    _producer = None