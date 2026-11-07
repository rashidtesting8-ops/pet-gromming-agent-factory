"""Backward-compatible shim for engine.service."""

from __future__ import annotations

from engine.service import (
    DATA_DIR,
    DB,
    ApprovePipelineRequest,
    CollectRequest,
    PipelineRequest,
    app,
    approve_pipeline_project,
    connect,
    create_job,
    create_pipeline_job,
    executor,
    fetch,
    get_job,
    health,
    lock,
    slots,
    store,
    work,
    work_pipeline,
)

__all__ = [
    "DATA_DIR",
    "DB",
    "ApprovePipelineRequest",
    "CollectRequest",
    "PipelineRequest",
    "app",
    "approve_pipeline_project",
    "connect",
    "create_job",
    "create_pipeline_job",
    "executor",
    "fetch",
    "get_job",
    "health",
    "lock",
    "slots",
    "store",
    "work",
    "work_pipeline",
]
