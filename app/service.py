"""Backward-compatible shim for engine.service."""

from __future__ import annotations

from engine.service import (
    DATA_DIR,
    DB,
    CollectRequest,
    app,
    connect,
    create_job,
    executor,
    fetch,
    get_job,
    health,
    lock,
    slots,
    store,
    work,
)

__all__ = [
    "DATA_DIR",
    "DB",
    "CollectRequest",
    "app",
    "connect",
    "create_job",
    "executor",
    "fetch",
    "get_job",
    "health",
    "lock",
    "slots",
    "store",
    "work",
]

