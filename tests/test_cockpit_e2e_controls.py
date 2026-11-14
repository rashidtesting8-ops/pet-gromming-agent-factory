"""API and UI tests for Cockpit end-to-end run_now and resume controls."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from app.cockpit import create_cockpit_app
from app.db import ProjectRecord, connect_db, init_db, upsert_project


def _asgi_call(
    app: Any,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    raw_headers = [(b"host", b"testserver")]
    if payload is not None:
        raw_headers.append((b"content-type", b"application/json"))

    status_code = 0
    chunks: list[bytes] = []

    async def _run() -> None:
        nonlocal status_code
        sent = False

        async def _receive() -> dict[str, Any]:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def _send(msg: dict[str, Any]) -> None:
            nonlocal status_code
            if msg["type"] == "http.response.start":
                status_code = int(msg["status"])
            elif msg["type"] == "http.response.body":
                chunks.append(msg.get("body", b""))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": raw_headers,
            "server": ("testserver", 80),
        }
        await app(scope, _receive, _send)

    asyncio.run(_run())
    return status_code, b"".join(chunks).decode("utf-8", errors="replace")


def test_cockpit_create_project_run_now_and_resume_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def _fake_run_pipeline(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return None

    import app.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "run_pipeline", _fake_run_pipeline)

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    app = create_cockpit_app(projects_dir=projects_dir)

    status, body = _asgi_call(
        app,
        "POST",
        "/api/projects",
        {
            "project_id": "cockpit-live-1",
            "business_name": "Cockpit Live Salon",
            "primary_url": "https://cockpitlive.example",
            "run_now": True,
        },
    )
    assert status == 200, body
    data = json.loads(body)
    assert data["project_id"] == "cockpit-live-1"
    assert data["job_started"] is True

    # Seed failed state and test resume endpoint
    conn = connect_db(projects_dir / "editvista.sqlite3")
    try:
        init_db(conn)
        upsert_project(
            conn,
            ProjectRecord(
                project_id="cockpit-live-1",
                business_name="Cockpit Live Salon",
                primary_url="https://cockpitlive.example",
                status="failed",
            ),
        )
    finally:
        conn.close()

    r_status, r_body = _asgi_call(app, "POST", "/api/projects/cockpit-live-1/resume", {})
    assert r_status == 200, r_body
    r_data = json.loads(r_body)
    assert r_data["status"] == "resuming"
    assert r_data["project_id"] == "cockpit-live-1"

    # Review UI includes resume job control
    html_status, html_body = _asgi_call(app, "GET", "/review/cockpit-live-1")
    assert html_status == 200
    assert "resume" in html_body.lower()
    assert "/api/projects/cockpit-live-1/resume" in html_body or "resumeJob" in html_body

