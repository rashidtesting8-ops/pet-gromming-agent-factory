"""Private n8n collector API. Bound to 127.0.0.1 by Docker Compose.

Bounded in-memory queue, durable SQLite statuses. Interrupted jobs remain
marked interrupted on restart instead of falsely saying they're running.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from engine.collector import collect, safe_url

app = FastAPI(title="Pet Grooming Asset Collector", docs_url="/docs")
executor = ThreadPoolExecutor(max_workers=2)
slots = BoundedSemaphore(4)
lock = Lock()
DATA_DIR = Path(os.environ.get("PROJECTS_DIR", "./projects"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = DATA_DIR / "_system" / "jobs.sqlite"
DB.parent.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=10)
    con.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    return con


def store(record: dict[str, Any]) -> None:
    with lock, connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO jobs (id, payload) VALUES (?,?)",
            (record["job_id"], json.dumps(record)),
        )


def fetch(job_id: str) -> dict[str, Any] | None:
    with lock, connect() as con:
        row = con.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
    return json.loads(row[0]) if row else None


with connect() as _db:
    for _id, _blob in _db.execute("SELECT id,payload FROM jobs").fetchall():
        _old = json.loads(_blob)
        if _old.get("status") in ("running", "queued"):
            _old.update(status="interrupted", error="Service restarted; resubmit to retry")
            _db.execute("UPDATE jobs SET payload=? WHERE id=?", (json.dumps(_old), _id))


class CollectRequest(BaseModel):
    url: str
    max_pages: int = Field(default=25, ge=1, le=40)
    max_media: int = Field(default=80, ge=1, le=120)


def work(job_id: str, req: CollectRequest) -> None:
    try:
        store({"job_id": job_id, "status": "running"})
        result = collect(req.url, DATA_DIR, req.max_pages, req.max_media)
        store({"job_id": job_id, "status": "done", "result": result})
    except Exception as exc:
        store({"job_id": job_id, "status": "failed", "error": str(exc)[:400]})
    finally:
        slots.release()


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/jobs", status_code=202)
def create_job(req: CollectRequest) -> dict[str, str]:
    try:
        safe_url(req.url)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    if not slots.acquire(blocking=False):
        raise HTTPException(429, "Collector busy; retry later")
    job_id = uuid.uuid4().hex
    payload = {"job_id": job_id, "status": "queued"}
    store(payload)
    try:
        executor.submit(work, job_id, req)
    except Exception:
        slots.release()
        raise
    return payload


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    rec = fetch(job_id)
    if rec is None:
        raise HTTPException(404, "Unknown job")
    return rec

