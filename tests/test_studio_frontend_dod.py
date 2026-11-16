"""TDD tests for the TypeScript Monograph Studio Cockpit and complete DoD browser controls."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.cockpit import create_cockpit_app
from tests.test_operator_cockpit import _scaffold_cockpit_project


def _asgi_req(
    app: Any,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, str], str]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    raw_headers = [(b"host", b"127.0.0.1")]
    if payload is not None:
        raw_headers.append((b"content-type", b"application/json"))

    status_code = 0
    resp_headers: dict[str, str] = {}
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
                for k, v in msg.get("headers", []):
                    resp_headers[k.decode("latin-1").lower()] = v.decode("latin-1")
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
            "server": ("127.0.0.1", 8888),
        }
        await app(scope, _receive, _send)

    asyncio.run(_run())
    return status_code, resp_headers, b"".join(chunks).decode("utf-8", errors="replace")


def test_typescript_sources_and_compiled_bundle_exist() -> None:
    root = Path(__file__).resolve().parent.parent
    ts_types = root / "frontend" / "src" / "types.ts"
    ts_studio = root / "frontend" / "src" / "studio.ts"
    tsconfig = root / "frontend" / "tsconfig.json"
    bundle = root / "app" / "static" / "studio.js"

    assert ts_types.is_file(), "Missing frontend/src/types.ts"
    assert ts_studio.is_file(), "Missing frontend/src/studio.ts"
    assert tsconfig.is_file(), "Missing frontend/tsconfig.json"
    assert bundle.is_file(), "Missing compiled app/static/studio.js"
    assert "EditVistaStudioController" in bundle.read_text(encoding="utf-8")


def test_studio_dod_status_section_inspector_and_bulk_rights_endpoints(
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "projects"
    _scaffold_cockpit_project(projects_dir, "studio-paws", rights_confirmed=False)
    app = create_cockpit_app(projects_dir=projects_dir)

    # 1. Static TypeScript bundle is served
    s_js, h_js, body_js = _asgi_req(app, "GET", "/static/studio.js")
    assert s_js == 200
    assert "javascript" in h_js.get("content-type", "")
    assert "EditVistaStudioController" in body_js

    # 2. DoD 8-Gate status endpoint
    s_dod, _, body_dod = _asgi_req(app, "GET", "/api/projects/studio-paws/dod-status")
    assert s_dod == 200
    dod = json.loads(body_dod)
    assert dod["project_id"] == "studio-paws"
    assert "gates" in dod
    assert "section_hashes" in dod
    assert dod["gates"]["rights_confirmed"] is False

    # 3. Section inspector endpoint returns canonical HTML + SHA-256
    s_sec, _, body_sec = _asgi_req(app, "GET", "/api/projects/studio-paws/section/hero")
    assert s_sec == 200
    sec_data = json.loads(body_sec)
    assert sec_data["section_name"] == "hero"
    assert "<section" in sec_data["html"]
    assert len(sec_data["sha256"]) == 64

    # 4. One-click confirm-all-rights unlocks rights gate
    s_all, _, body_all = _asgi_req(
        app,
        "POST",
        "/api/projects/studio-paws/confirm-all-rights",
        {"basis": "owner_permission", "operator": "Lead Architect"},
    )
    assert s_all == 200, body_all
    _, _, body_dod2 = _asgi_req(app, "GET", "/api/projects/studio-paws/dod-status")
    assert json.loads(body_dod2)["gates"]["rights_confirmed"] is True

    # 5. Dashboard & Review templates use Monograph Editorial design (no #0F172A slate slop)
    s_dash, _, html_dash = _asgi_req(app, "GET", "/dashboard")
    assert s_dash == 200
    assert 'data-ev-studio="monograph"' in html_dash
    assert "#0F172A" not in html_dash

    s_rev, _, html_rev = _asgi_req(app, "GET", "/review/studio-paws")
    assert s_rev == 200
    assert 'data-ev-studio="monograph"' in html_rev
    assert 'data-ev-dod-ledger="true"' in html_rev
    assert 'data-ev-viewport-switcher="true"' in html_rev
    assert "/static/studio.js" in html_rev
    assert "#0F172A" not in html_rev
