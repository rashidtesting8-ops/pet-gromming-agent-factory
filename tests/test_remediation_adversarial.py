"""Adversarial regression tests for Senior Engineering Audit findings F1, F3, F5, F7."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from app.approval import (
    ReleaseApprovalGateError,
    approve_release,
    export_approved_deliverables,
)
from app.cockpit import create_cockpit_app
from app.curator import (
    MAX_SAFE_IMAGE_PIXELS,
    compute_perceptual_hash,
    curate_project_images,
    hamming_distance_hex,
)
from app.db import ProjectRecord, connect_db, init_db, upsert_project
from app.ghl_exporter import scope_css
from app.reviser import apply_targeted_revisions
from app.rights import confirm_asset_rights
from app.visual_critic import run_visual_critic
from PIL import Image
from src.engine.llm.adapter import BudgetConfig, FakeProvider, LLMAdapter, LLMResponse


def _seed_approvable_project(tmp_path: Path, *, with_image: bool = False) -> Path:
    proj = tmp_path / "projects" / "adv-salon"
    for sub in (
        "research",
        "website",
        "website/assets",
        "website/css",
        "website/sections",
        "qa",
        "qa/screenshots",
        "release-candidate",
    ):
        (proj / sub).mkdir(parents=True, exist_ok=True)

    (proj / "research" / "business-facts.json").write_text(
        json.dumps(
            {
                "project_id": "adv-salon",
                "facts": [
                    {
                        "fact_id": "f1",
                        "category": "business_name",
                        "claim_value": "Adv Salon",
                        "source_url": "https://example.com",
                        "source_text_snippet": "Adv Salon",
                        "is_verified": True,
                        "status": "verified",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (proj / "website" / "brand-identity.json").write_text(
        json.dumps({"business_name": "Adv Salon", "primary_color": "#1B365D"}),
        encoding="utf-8",
    )

    img_tag = ""
    if with_image:
        img_bytes = b"fake-jpeg-bytes"
        (proj / "assets" / "optimized").mkdir(parents=True, exist_ok=True)
        (proj / "assets" / "optimized" / "hero.jpg").write_bytes(img_bytes)
        (proj / "website" / "assets" / "optimized").mkdir(parents=True, exist_ok=True)
        (proj / "website" / "assets" / "optimized" / "hero.jpg").write_bytes(img_bytes)
        rc_assets = proj / "release-candidate" / "assets" / "optimized"
        rc_assets.mkdir(parents=True, exist_ok=True)
        (rc_assets / "hero.jpg").write_bytes(img_bytes)
        sha = hashlib.sha256(img_bytes).hexdigest()
        (proj / "research" / "asset-manifest.json").write_text(
            json.dumps(
                [
                    {
                        "asset_id": "hero-1",
                        "file": "assets/optimized/hero.jpg",
                        "url": "https://example.com/hero.jpg",
                        "sha256": sha,
                        "rights_confirmed_for_preview": True,
                    }
                ]
            ),
            encoding="utf-8",
        )
        img_tag = '<img src="assets/optimized/hero.jpg" alt="Adv Salon">'

    hero_sec = f'<section id="hero" data-section="hero"><h1>Adv Salon</h1>{img_tag}</section>'
    (proj / "website" / "sections" / "hero.html").write_text(hero_sec, encoding="utf-8")
    html_doc = (
        "<!doctype html><html><head><style>:root{--ev-primary:#1B365D;}</style></head>"
        f"<body><main>{hero_sec}</main></body></html>"
    )
    (proj / "website" / "index.html").write_text(html_doc, encoding="utf-8")
    (proj / "website" / "css" / "styles.css").write_text(
        ":root{--ev-primary:#1B365D;}", encoding="utf-8"
    )
    (proj / "release-candidate" / "standalone.html").write_text(html_doc, encoding="utf-8")
    (proj / "release-candidate" / "approved-homepage.html").write_text(html_doc, encoding="utf-8")
    (proj / "release-candidate" / "ghl-ready.html").write_text(
        '<div id="ev-adv-salon">Adv Salon</div>', encoding="utf-8"
    )
    (proj / "research" / "retained-assets.json").write_text(
        json.dumps({"retained": []}), encoding="utf-8"
    )
    cand_sha = hashlib.sha256(html_doc.encode("utf-8")).hexdigest()

    (proj / "qa" / "qa-report.json").write_text(
        json.dumps(
            {
                "passed": True,
                "critical_defects": [],
                "candidate_sha256": cand_sha,
            }
        ),
        encoding="utf-8",
    )
    (proj / "qa" / "visual-critique.json").write_text(
        json.dumps({"project_id": "adv-salon", "status": "passed", "defects": []}),
        encoding="utf-8",
    )
    return proj


def test_f1_short_approval_token_cannot_bypass_export_gate(tmp_path: Path) -> None:
    proj = _seed_approvable_project(tmp_path)
    with pytest.raises(ReleaseApprovalGateError):
        export_approved_deliverables(proj, approval_token="abcd")


def test_f1_corrupted_visual_critique_blocks_approval(tmp_path: Path) -> None:
    proj = _seed_approvable_project(tmp_path)
    (proj / "qa" / "visual-critique.json").write_text("{corrupt json", encoding="utf-8")
    with pytest.raises(ReleaseApprovalGateError, match="visual-critique.json"):
        approve_release(proj, operator_name="Reviewer")


def test_f1_missing_rights_audit_blocks_approval_when_assets_used(tmp_path: Path) -> None:
    proj = _seed_approvable_project(tmp_path, with_image=True)
    conn = connect_db(proj.parent / "editvista.sqlite3")
    try:
        init_db(conn)
        upsert_project(
            conn,
            ProjectRecord(
                project_id=proj.name,
                business_name="Adv Salon",
                primary_url="https://example.com",
                status="awaiting_approval",
            ),
        )
    finally:
        conn.close()

    with pytest.raises(ReleaseApprovalGateError, match="rights-audit.jsonl"):
        approve_release(proj, operator_name="Reviewer")

    # Recording rights audit signature unlocks approval
    confirm_asset_rights(
        proj,
        asset="hero.jpg",
        basis="owner_permission",
        operator="Reviewer",
        evidence="written consent",
    )
    manifest_hash = approve_release(proj, operator_name="Reviewer")
    assert len(manifest_hash) == 64


def _asgi_post(
    app: Any, path: str, payload: dict[str, Any], headers: dict[str, str] | None = None
) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    raw_headers = [
        (b"content-type", b"application/json"),
        (b"host", b"testserver"),
    ]
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode("ascii"), v.encode("ascii")))

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
            "method": "POST",
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


def test_f1_cockpit_approve_requires_bearer_token_when_configured(tmp_path: Path) -> None:
    proj = _seed_approvable_project(tmp_path)
    conn = connect_db(proj.parent / "editvista.sqlite3")
    try:
        init_db(conn)
        upsert_project(
            conn,
            ProjectRecord(
                project_id=proj.name,
                business_name="Adv Salon",
                primary_url="https://example.com",
                status="awaiting_approval",
            ),
        )
    finally:
        conn.close()

    app = create_cockpit_app(
        projects_dir=proj.parent,
        api_token="super-secret-operator-token",
    )

    unauth_status, _ = _asgi_post(
        app,
        f"/api/projects/{proj.name}/approve",
        {"operator_name": "Reviewer", "version": "v1"},
    )
    assert unauth_status == 401

    auth_status, auth_body = _asgi_post(
        app,
        f"/api/projects/{proj.name}/approve",
        {"operator_name": "Reviewer", "version": "v1"},
        headers={"Authorization": "Bearer super-secret-operator-token"},
    )
    assert auth_status == 200, auth_body


def test_f3_visual_critic_failure_sets_unavailable_and_blocks_approval(tmp_path: Path) -> None:
    proj = _seed_approvable_project(tmp_path)
    shot = proj / "qa" / "screenshots" / "desktop_1440.png"
    Image.new("RGB", (100, 100), color=(240, 240, 240)).save(shot)

    class _ExplodingVisionProvider(FakeProvider):
        supports_vision: bool = True

        def complete(
            self,
            prompt: str,
            images: Sequence[bytes | Path] = (),
            model: str | None = None,
            **kwargs: Any,
        ) -> LLMResponse:
            raise RuntimeError("upstream 503")

    adapter = LLMAdapter(
        _ExplodingVisionProvider(),
        config=BudgetConfig(
            cache_dir=tmp_path / ".cache",
            ledger_path=tmp_path / "ledger.jsonl",
            db_path=tmp_path / "budget.sqlite3",
        ),
    )
    report = run_visual_critic(proj, llm_adapter=adapter)
    assert report.status == "unavailable"
    assert "upstream 503" in (report.error_message or "")

    with pytest.raises(ReleaseApprovalGateError, match="unavailable"):
        approve_release(proj, operator_name="Reviewer")


def test_f3_non_vision_provider_raises_fast_on_images(tmp_path: Path) -> None:
    provider = FakeProvider(supports_vision=False)
    adapter = LLMAdapter(
        provider,
        config=BudgetConfig(
            cache_dir=tmp_path / ".cache",
            ledger_path=tmp_path / "ledger.jsonl",
            db_path=tmp_path / "budget.sqlite3",
        ),
    )
    with pytest.raises(ValueError, match="supports_vision=False"):
        adapter.complete(
            prompt="inspect",
            images=[b"fake-png-bytes"],
            project_id="adv-salon",
            stage="visual_critic",
        )


def test_f5_reviser_only_patches_requested_css_property(tmp_path: Path) -> None:
    proj = _seed_approvable_project(tmp_path)
    (proj / "qa" / "visual-critique.json").write_text(
        json.dumps(
            {
                "project_id": "adv-salon",
                "status": "defects_found",
                "inspected_screenshots": ["qa/screenshots/1440px.png"],
                "defects": [
                    {
                        "target_section_id": "hero",
                        "screenshot_path": "qa/screenshots/1440px.png",
                        "defect_type": "spacing_and_whitespace_rhythm",
                        "actionable_instruction": "Increase padding on #hero.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    res = apply_targeted_revisions(proj)
    assert "hero" in res.modified_section_ids
    css = (proj / "website" / "css" / "styles.css").read_text(encoding="utf-8")
    assert "padding:" in css
    assert "background:" not in css and "background-color:" not in css


def test_f7_curator_perceptual_dedupe_and_decompression_bomb_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Create two visually identical images encoded differently (PNG vs JPEG)
    img = Image.new("RGB", (900, 600), color=(30, 80, 140))
    for x in range(0, 450):
        for y in range(0, 600):
            img.putpixel((x, y), (220, 180, 60))

    p1 = tmp_path / "a.png"
    p2 = tmp_path / "b.jpg"
    img.save(p1, format="PNG")
    img.resize((800, 533)).save(p2, format="JPEG", quality=85)

    with Image.open(p1) as im1, Image.open(p2) as im2:
        h1 = compute_perceptual_hash(im1)
        h2 = compute_perceptual_hash(im2)
    assert h1 and h2 and hamming_distance_hex(h1, h2) <= 8

    # Oversized pixel bomb guard in curate_project_images
    proj = _seed_approvable_project(tmp_path)
    opt_dir = proj / "assets" / "optimized"
    opt_dir.mkdir(parents=True, exist_ok=True)
    img.save(opt_dir / "good_dog_portrait.png", format="PNG")
    img.resize((800, 533)).save(opt_dir / "dup_dog_portrait.jpg", format="JPEG")
    (opt_dir / "bomb.png").write_bytes(b"not-checked-before-open")

    orig_open = Image.open

    def _mock_open(fp: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(str(fp)).name == "bomb.png":
            raise Image.DecompressionBombError(
                f"Image size exceeds limit of {MAX_SAFE_IMAGE_PIXELS} pixels"
            )
        return orig_open(fp, *args, **kwargs)

    monkeypatch.setattr(Image, "open", _mock_open)
    report = curate_project_images(proj)
    selected = (
        ([report.hero_image] if report.hero_image else [])
        + list(report.grooming_gallery)
        + ([report.salon_facility_or_van] if report.salon_facility_or_van else [])
    )
    selected_names = {c.filename for c in selected}
    assert "bomb.png" not in selected_names
    assert len(selected_names) == 1  # dup_dog_portrait.jpg deduped against good_dog_portrait.png
    assert any(e.filename == "bomb.png" for e in report.excluded_images)


def test_f7_ghl_exporter_namespaces_keyframes() -> None:
    css = (
        "@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }\n"
        ".card { animation: fadeIn 0.4s ease-in; }\n"
        ".title { animation-name: fadeIn; }\n"
    )
    scoped = scope_css(css, root_selector="#ev-biz")
    assert "@keyframes ev-biz-kf-fadeIn" in scoped
    assert "animation: ev-biz-kf-fadeIn 0.4s ease-in;" in scoped
    assert "animation-name: ev-biz-kf-fadeIn;" in scoped
