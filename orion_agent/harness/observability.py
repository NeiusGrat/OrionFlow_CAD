"""Lightweight structured logging + per-turn timing for the harness.

Stdlib ``logging`` with a JSON formatter so logs are greppable and ingestible,
plus a ``turn_timer`` context manager that records per-stage durations. No
third-party logging dependency, so this works in the addon too if needed.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from typing import Any


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def get_logger(name: str = "orion.harness", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    return logger


def log_event(logger: logging.Logger, msg: str, **fields) -> None:
    record = logging.LogRecord(
        logger.name, logging.INFO, __file__, 0, msg, None, None
    )
    record.extra_fields = fields
    logger.handle(record)


@contextmanager
def turn_timer():
    """Collect per-stage timings within an agent turn."""
    stages: dict[str, float] = {}
    state = {"_start": time.time(), "_last": time.time()}

    def mark(stage: str):
        now = time.time()
        stages[stage] = round((now - state["_last"]) * 1000, 1)
        state["_last"] = now

    try:
        yield mark, stages
    finally:
        stages["total_ms"] = round((time.time() - state["_start"]) * 1000, 1)
