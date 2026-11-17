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


def test_studio_9stage_telemetry_and_guide_ui(tmp_path: Path) -> None:
    from app.db import JobRunRecord, ProjectRecord, connect_db, init_db, upsert_project

    projects_dir = tmp_path / "projects"
    _scaffold_cockpit_project(projects_dir, "studio-paws", rights_confirmed=True)
    app = create_cockpit_app(projects_dir=projects_dir)

    # 1. Completed/staged artifacts project returns 9 canonical PDF stages
    s_stg, _, body_stg = _asgi_req(app, "GET", "/api/projects/studio-paws/stages")
    assert s_stg == 200, body_stg
    data = json.loads(body_stg)
    assert data["project_id"] == "studio-paws"
    stages = data["stages"]
    assert len(stages) == 9
    expected_modules = [
        "intake",
        "collect",
        "extract",
        "curate",
        "art_director",
        "generate",
        "critique",
        "qa",
        "signoff",
    ]
    assert [s["module"] for s in stages] == expected_modules
    for st in stages:
        assert st["plain_title"]
        assert st["plain_analogy"]
        assert st["pdf_spec"]
        assert st["status"] in ("pending", "running", "completed", "failed", "needs_review")
        assert "evidence" in st

    # 2. Failed mid-pipeline job_runs reflects exact failure stage telemetry
    db_path = projects_dir / "editvista.sqlite3"
    fail_dir = projects_dir / "failing-paws"
    fail_dir.mkdir(parents=True, exist_ok=True)
    conn = connect_db(db_path)
    try:
        init_db(conn)
        upsert_project(
            conn,
            ProjectRecord(
                project_id="failing-paws",
                business_name="Failing Paws",
                primary_url="https://failingpaws.example",
                status="failed",
            ),
        )
        for rec in (
            JobRunRecord(
                run_id="r1",
                project_id="failing-paws",
                module_name="collect",
                status="completed",
                idempotency_key="k1",
            ),
            JobRunRecord(
                run_id="r2",
                project_id="failing-paws",
                module_name="extract",
                status="failed",
                idempotency_key="k2",
                error_message="Timeout parsing pricing table",
            ),
        ):
            conn.execute(
                """
                INSERT INTO job_runs
                  (run_id, project_id, module_name, status, idempotency_key,
                   error_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.run_id,
                    rec.project_id,
                    rec.module_name,
                    rec.status,
                    rec.idempotency_key,
                    rec.error_message,
                    rec.created_at.isoformat(),
                    rec.updated_at.isoformat(),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    s_fail, _, body_fail = _asgi_req(app, "GET", "/api/projects/failing-paws/stages")
    assert s_fail == 200, body_fail
    fail_stages = {s["module"]: s for s in json.loads(body_fail)["stages"]}
    assert fail_stages["collect"]["status"] == "completed"
    assert fail_stages["extract"]["status"] == "failed"
    assert "Timeout parsing pricing table" in fail_stages["extract"]["evidence"]

    # 3. Dashboard & Review templates expose non-technical 9-stage guide + live stepper UI
    _, _, html_dash = _asgi_req(app, "GET", "/dashboard")
    assert 'data-ev-blueprint-bar="true"' in html_dash
    assert 'data-ev-live-stepper="true"' in html_dash
    assert "togglePipelineGuide" in html_dash
    assert "openStageMonitor" in html_dash

    _, _, html_rev = _asgi_req(app, "GET", "/review/studio-paws")
    assert 'data-ev-live-stepper="true"' in html_rev
    assert "openStageMonitor" in html_rev

    # 4. Compiled studio.js contains live stepper and guide methods
    _, _, js_body = _asgi_req(app, "GET", "/static/studio.js")
    assert "openStageMonitor" in js_body
    assert "togglePipelineGuide" in js_body


def test_pre_approval_prune_plan_and_conflict_name_sanitization(tmp_path: Path) -> None:
    from app.art_director import generate_art_direction
    from app.generator import generate_website

    projects_dir = tmp_path / "projects"
    _scaffold_cockpit_project(projects_dir, "draft-paws", rights_confirmed=False)
    proj = projects_dir / "draft-paws"
    # Simulate an unapproved draft (remove delivery/ so it stays pre-approval)
    import shutil

    if (proj / "delivery").exists():
        shutil.rmtree(proj / "delivery")

    # Inject a conflicted business_name into business-facts.json to test sanitization barrier
    facts_path = proj / "research" / "business-facts.json"
    facts_payload = json.loads(facts_path.read_text(encoding="utf-8"))
    facts_payload["facts"].insert(
        0,
        {
            "fact_id": "f-conflict-name",
            "project_id": "draft-paws",
            "category": "business_name",
            "claim_key": "business_name",
            "claim_value": (
                "Draft Paws Salon (conflicts with Home - Draft Paws, Cookies Policy - Draft Paws)"
            ),
            "source_url": "https://draftpaws.example/",
            "source_text_snippet": "Draft Paws Salon",
            "is_verified": False,
            "status": "needs_review",
        },
    )
    facts_path.write_text(json.dumps(facts_payload, indent=2), encoding="utf-8")

    # Run art direction + generation: rendered HTML must NEVER contain "(conflicts with"
    generate_art_direction(proj)
    generate_website(proj)
    rendered_html = (proj / "website" / "index.html").read_text(encoding="utf-8")
    assert "conflicts with" not in rendered_html.lower()
    assert "cookies policy" not in rendered_html.lower()

    # Pre-approval Cockpit prune plan returns non-blocking 200 summary instead of error
    app = create_cockpit_app(projects_dir=projects_dir)
    s_plan, _, b_plan = _asgi_req(app, "POST", "/api/projects/draft-paws/prune", {"mode": "plan"})
    assert s_plan == 200, b_plan
    plan_data = json.loads(b_plan)
    assert plan_data["mode"] == "plan"
    assert plan_data["pre_approval"] is True
    assert "Approve & Freeze Release" in plan_data["note"]

    # Destructive prune remains strictly blocked before approval with clear guidance
    s_prn, _, b_prn = _asgi_req(app, "POST", "/api/projects/draft-paws/prune", {"mode": "prune"})
    assert s_prn == 400
    assert "Approve & Freeze Release" in b_prn

    _, _, html_rev = _asgi_req(app, "GET", "/review/draft-paws")
    assert 'id="ev-btn-safe-prune"' in html_rev
