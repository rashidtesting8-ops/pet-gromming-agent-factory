"""Regression tests for all Critical/High findings in the security code review."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from app.cockpit import create_cockpit_app
from src.engine.service import _container_safe_qa_runner
from src.engine.service import app as service_app


def _asgi_request(
    app: Any,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], str]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    raw_headers = [(b"host", b"127.0.0.1")]
    if payload is not None:
        raw_headers.append((b"content-type", b"application/json"))
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode("ascii"), v.encode("ascii")))

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


def test_critical_1_qa_runner_never_fabricates_passed_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj = tmp_path / "broken-qa"
    (proj / "website").mkdir(parents=True, exist_ok=True)
    (proj / "website" / "index.html").write_text("<html><body>Hi</body></html>", encoding="utf-8")

    import app.pipeline as pipe_mod

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Chromium failed to launch")

    monkeypatch.setattr(pipe_mod, "run_qa_engine", _boom)

    with pytest.raises(RuntimeError, match="Chromium failed to launch"):
        _container_safe_qa_runner(proj)

    assert not (proj / "qa" / "qa-report.json").exists()


def test_critical_2_cockpit_blocks_research_traversal_and_sandboxes_svg(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    proj = projects_dir / "sec-salon"
    (proj / "research").mkdir(parents=True, exist_ok=True)
    (proj / "assets" / "optimized").mkdir(parents=True, exist_ok=True)
    (proj / "website").mkdir(parents=True, exist_ok=True)
    (proj / "research" / "business-facts.json").write_text('{"secret": true}', encoding="utf-8")
    (proj / "assets" / "optimized" / "evil.svg").write_text(
        "<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
        encoding="utf-8",
    )
    (proj / "website" / "index.html").write_text("<html><body>Hi</body></html>", encoding="utf-8")

    cockpit = create_cockpit_app(projects_dir=projects_dir)

    s1, _, _ = _asgi_request(cockpit, "GET", "/preview/sec-salon/research/business-facts.json")
    assert s1 == 404

    s2, _, _ = _asgi_request(cockpit, "GET", "/assets/sec-salon/research/business-facts.json")
    assert s2 == 404

    s3, h3, _ = _asgi_request(cockpit, "GET", "/assets/sec-salon/assets/optimized/evil.svg")
    assert s3 == 200
    assert "sandbox" in h3.get("content-security-policy", "")
    assert h3.get("x-content-type-options") == "nosniff"
    assert "attachment" in h3.get("content-disposition", "")

    s4, h4, _ = _asgi_request(cockpit, "GET", "/preview/sec-salon/index.html")
    assert s4 == 200
    assert "sandbox" in h4.get("content-security-policy", "")
    assert h4.get("x-content-type-options") == "nosniff"


def test_high_4_get_endpoints_require_token_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_dir = tmp_path / "projects"
    (projects_dir / "sec-salon").mkdir(parents=True, exist_ok=True)
    cockpit = create_cockpit_app(projects_dir=projects_dir, api_token="top-secret-token")

    # Health stays open
    h_status, _, _ = _asgi_request(cockpit, "GET", "/api/health")
    assert h_status == 200

    # Protected GET requires token
    unauth_status, _, _ = _asgi_request(cockpit, "GET", "/api/projects/sec-salon/summary")
    assert unauth_status == 401

    auth_status, _, _ = _asgi_request(
        cockpit,
        "GET",
        "/api/projects/sec-salon/summary",
        headers={"Authorization": "Bearer top-secret-token"},
    )
    assert auth_status == 200

    # Service GET /jobs/{id} also requires token when EDITVISTA_API_TOKEN is set
    monkeypatch.setenv("EDITVISTA_API_TOKEN", "svc-secret-token")
    svc_unauth, _, _ = _asgi_request(service_app, "GET", "/jobs/does-not-exist")
    assert svc_unauth == 401

    svc_auth, _, _ = _asgi_request(
        service_app,
        "GET",
        "/jobs/does-not-exist",
        headers={"Authorization": "Bearer svc-secret-token"},
    )
    assert svc_auth == 404


def test_suggestion_2_service_sanitizes_internal_job_error_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.engine.service as srv

    monkeypatch.setattr(srv, "DB", tmp_path / "jobs.sqlite")
    monkeypatch.setattr(srv, "DATA_DIR", tmp_path / "projects")

    def _explode(**kwargs: Any) -> Any:
        raise RuntimeError(
            "Fatal crash at C:\\Users\\Admin\\secret\\db.sqlite "
            "with key sk-or-v1-999999999999999999"
        )

    monkeypatch.setattr(srv, "_run_full_pipeline_sync", _explode)
    srv.slots.acquire(blocking=False)
    srv.work_pipeline("job-err-1", srv.PipelineRequest(url="https://example.com"))
    rec = srv.fetch("job-err-1")
    assert rec is not None
    assert rec["status"] == "failed"
    assert "C:\\Users\\Admin" not in rec["error"]
    assert "sk-or-v1-" not in rec["error"]


def test_suggestion_3_collector_sanitizes_downloaded_svg_scripts_and_handlers() -> None:
    from src.engine.collector import sanitize_svg_bytes

    malicious_svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="fetch(\'/approve\')">'
        b"<script>alert(1)</script>"
        b'<foreignObject><iframe></iframe></foreignObject>'
        b'<a href="javascript:evil()"><rect width="10" height="10"/></a>'
        b"</svg>"
    )
    cleaned = sanitize_svg_bytes(malicious_svg).decode("utf-8")
    assert "<script" not in cleaned.lower()
    assert "foreignobject" not in cleaned.lower()
    assert "onload" not in cleaned.lower()
    assert "javascript:" not in cleaned.lower()
    assert "<rect" in cleaned.lower()


def test_suggestion_6_cockpit_enforces_strict_project_id_slug_regex(tmp_path: Path) -> None:
    cockpit = create_cockpit_app(projects_dir=tmp_path / "projects")
    for bad_id in (".hidden", "bad slug!@#", "-leading-dash", "Upper_Case"):
        status, _, _ = _asgi_request(
            cockpit,
            "POST",
            "/api/projects",
            {"project_id": bad_id, "business_name": "Test"},
        )
        assert status == 400, f"Expected 400 for {bad_id!r}, got {status}"


def test_issue_4_n8n_workflows_include_api_token_header() -> None:
    n8n_dir = Path(__file__).resolve().parent.parent / "n8n"
    for wf_path in sorted(n8n_dir.glob("*.json")):
        raw = wf_path.read_text(encoding="utf-8")
        assert "EDITVISTA_API_TOKEN" in raw, f"Missing EDITVISTA_API_TOKEN header in {wf_path.name}"
