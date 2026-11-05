"""Unit tests for Human Review Package (app/approval.py) and Cleanup (app/cleanup.py)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from app.approval import (
    ReleaseApprovalGateError,
    approve_and_freeze_release,
    export_approved_deliverables,
    generate_review_summary,
)
from app.cleanup import cleanup, safe_prune_project
from app.db import ProjectRecord, connect_db, get_project, init_db, upsert_project


def _scaffold_reviewable_project(
    tmp_path: Path,
    project_id: str = "luxe-paws",
) -> tuple[Path, Path]:
    projects_dir = tmp_path / "projects"
    project_root = projects_dir / project_id
    db_path = projects_dir / "editvista.sqlite3"

    for sub in (
        "assets/website",
        "assets/instagram",
        "assets/optimized",
        "research",
        "design",
        "website/css",
        "website/js",
        "qa/screenshots",
        "delivery",
        "tmp",
    ):
        (project_root / sub).mkdir(parents=True, exist_ok=True)

    # DB record
    conn = connect_db(db_path)
    try:
        init_db(conn)
        upsert_project(
            conn,
            ProjectRecord(
                project_id=project_id,
                business_name="Luxe Paws Grooming",
                primary_url="https://luxepaws.example/",
                status="completed",
            ),
        )
    finally:
        conn.close()

    # Assets: 1 retained hero asset, 2 unreferenced raw staging files, 1 temp scraper file
    (project_root / "assets/optimized/hero_dog.jpg").write_bytes(b"retained-hero-bytes")
    (project_root / "assets/website/raw_unused_1.jpg").write_bytes(b"unused-website-bytes")
    (project_root / "assets/instagram/raw_unused_reel.mp4").write_bytes(b"unused-insta-bytes")
    (project_root / "tmp/scraper_stage.tmp").write_bytes(b"temp-working-file")

    # Facts (2 verified, 1 needs_review)
    facts_payload = {
        "project_id": project_id,
        "extracted_at": "2026-11-05T12:00:00Z",
        "prompt_injection_warnings": [],
        "facts": [
            {
                "fact_id": "f1",
                "project_id": project_id,
                "category": "business_name",
                "claim_key": "business_name",
                "claim_value": "Luxe Paws Grooming",
                "source_url": "https://luxepaws.example/",
                "source_text_snippet": "Luxe Paws Grooming",
                "is_verified": True,
                "status": "verified",
                "last_checked_at": "2026-11-05T12:00:00Z",
            },
            {
                "fact_id": "f2",
                "project_id": project_id,
                "category": "phone",
                "claim_key": "phone",
                "claim_value": "(512) 555-0190",
                "source_url": "https://luxepaws.example/",
                "source_text_snippet": "Call (512) 555-0190",
                "is_verified": True,
                "status": "verified",
                "last_checked_at": "2026-11-05T12:00:00Z",
            },
            {
                "fact_id": "f3",
                "project_id": project_id,
                "category": "pricing",
                "claim_key": "price_deluxe",
                "claim_value": "$120",
                "source_url": "https://luxepaws.example/",
                "source_text_snippet": "Unverified",
                "is_verified": False,
                "status": "needs_review",
                "last_checked_at": "2026-11-05T12:00:00Z",
            },
        ],
    }
    (project_root / "research/business-facts.json").write_text(
        json.dumps(facts_payload), encoding="utf-8"
    )

    # Asset manifest with rights_confirmed_for_preview
    asset_manifest = [
        {
            "file": "assets/optimized/hero_dog.jpg",
            "sha256": "abc123def456",
            "url": "https://luxepaws.example/hero_dog.jpg",
            "status": "downloaded",
            "rights_confirmed_for_preview": True,
        }
    ]
    (project_root / "research/asset-manifest.json").write_text(
        json.dumps(asset_manifest), encoding="utf-8"
    )

    # 5-viewport screenshots & QA report
    for width in (1440, 1024, 768, 390, 360):
        (project_root / "qa/screenshots" / f"{width}px.png").write_bytes(b"png-bytes")

    (project_root / "qa/qa-report.json").write_text(
        json.dumps({"project_id": project_id, "passed": True, "viewports": []}),
        encoding="utf-8",
    )
    (project_root / "qa/visual-critique.json").write_text(
        json.dumps({"project_id": project_id, "status": "passed", "defects": []}),
        encoding="utf-8",
    )

    # Website files
    (project_root / "website/index.html").write_text(
        '<!DOCTYPE html><html><head><link rel="stylesheet" href="css/styles.css"></head>'
        '<body><main><img src="../assets/optimized/hero_dog.jpg" alt="Hero"></main>'
        '<script src="js/main.js"></script></body></html>',
        encoding="utf-8",
    )
    (project_root / "website/css/styles.css").write_text(
        ":root { --ev-primary: #1B365D; }\nmain { padding: 2rem; }\n",
        encoding="utf-8",
    )
    (project_root / "website/js/main.js").write_text(
        "var ready = true;\n",
        encoding="utf-8",
    )

    # Retained assets manifest
    (project_root / "delivery/retained-assets.json").write_text(
        json.dumps({"approved": True, "assets": ["assets/optimized/hero_dog.jpg"]}),
        encoding="utf-8",
    )

    return projects_dir, project_root


def test_cleanup_aborts_if_project_not_approved_or_archive_missing(tmp_path: Path) -> None:
    """Cleanup and deliverable export must abort if project is unapproved or archive is missing."""
    projects_dir, project_root = _scaffold_reviewable_project(tmp_path, "unapproved-salon")

    # 1. Delivery release gate blocks export when is_approved=False and no approval_token is passed
    with pytest.raises(ReleaseApprovalGateError):
        export_approved_deliverables(project_root, is_approved=False, approval_token=None)

    # 2. Cleanup aborts when deliverables / archive do not exist
    with pytest.raises(ValueError):
        cleanup(project_root, mode="prune", confirm=True)

    with pytest.raises(ValueError, match="archive"):
        safe_prune_project(project_root, dry_run=False)

    assert projects_dir.is_dir()


def test_release_manifest_hash_changes_when_html_or_css_altered(tmp_path: Path) -> None:
    """approve_and_freeze_release must compute deterministic SHA-256 tree that changes on edits."""
    projects_dir, project_root = _scaffold_reviewable_project(tmp_path, "hash-freeze-salon")

    # Inspect review summary first
    summary = generate_review_summary("hash-freeze-salon", projects_dir=projects_dir)
    assert summary["fact_metrics"]["verified_count"] == 2
    assert summary["fact_metrics"]["needs_review_count"] == 1
    assert len(summary["screenshots"]) == 5
    assert summary["technical_qa_passed"] is True
    assert summary["visual_critique_status"] == "passed"

    # First approval & freeze
    version_hash_1 = approve_and_freeze_release(
        "hash-freeze-salon",
        operator_name="Alice Reviewer",
        notes="Initial human sign-off",
        projects_dir=projects_dir,
    )
    manifest_path = project_root / "delivery" / "release-manifest.json"
    assert manifest_path.is_file()
    manifest_1 = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_1["version_hash"] == version_hash_1
    assert manifest_1["operator_name"] == "Alice Reviewer"

    # Verify SQLite project status is now 'approved'
    conn = connect_db(projects_dir / "editvista.sqlite3")
    try:
        proj = get_project(conn, "hash-freeze-salon")
        assert proj is not None
        assert proj.status == "approved"
    finally:
        conn.close()

    # Alter a CSS file in website/css/styles.css and re-freeze
    (project_root / "website/css/styles.css").write_text(
        ":root { --ev-primary: #D98A2B; }\nmain { padding: 3rem; }\n",
        encoding="utf-8",
    )
    version_hash_2 = approve_and_freeze_release(
        "hash-freeze-salon",
        operator_name="Alice Reviewer",
        notes="Updated primary color token",
        projects_dir=projects_dir,
    )
    assert version_hash_2 != version_hash_1


def test_retained_assets_and_delivery_files_never_touched_by_cleanup(tmp_path: Path) -> None:
    """Cleanup deletes unreferenced staging files while preserving retained-assets and delivery/."""
    projects_dir, project_root = _scaffold_reviewable_project(tmp_path, "prune-safe-salon")

    # Approve and freeze release (creates projects/_archives/prune-safe-salon-approved.zip)
    approve_and_freeze_release(
        "prune-safe-salon",
        operator_name="Bob Release Lead",
        notes="Approved for final delivery and staging cleanup",
        projects_dir=projects_dir,
    )

    archive_zip = projects_dir / "_archives" / "prune-safe-salon-approved.zip"
    assert archive_zip.is_file()

    # Dry-run mode returns eligible staging/temp files without deleting them
    dry_plan = safe_prune_project(project_root, dry_run=True)
    assert "assets/website/raw_unused_1.jpg" in dry_plan["eligible_for_deletion"]
    assert "assets/instagram/raw_unused_reel.mp4" in dry_plan["eligible_for_deletion"]
    assert "tmp/scraper_stage.tmp" in dry_plan["eligible_for_deletion"]
    assert "assets/optimized/hero_dog.jpg" not in dry_plan["eligible_for_deletion"]
    assert (project_root / "assets/website/raw_unused_1.jpg").is_file()

    # Execute mode deletes only unreferenced staging and tmp files
    exec_res = safe_prune_project(project_root, dry_run=False)
    assert exec_res["deleted_count"] >= 3

    # Unreferenced staging & temp files are deleted
    assert not (project_root / "assets/website/raw_unused_1.jpg").exists()
    assert not (project_root / "assets/instagram/raw_unused_reel.mp4").exists()
    assert not (project_root / "tmp/scraper_stage.tmp").exists()

    # Retained assets and delivery/ files are NEVER touched
    assert (project_root / "assets/optimized/hero_dog.jpg").is_file()
    assert (project_root / "delivery/approved-homepage.html").is_file()
    assert (project_root / "delivery/ghl-ready.html").is_file()
    assert (project_root / "delivery/retained-assets.json").is_file()
    assert (project_root / "delivery/release-manifest.json").is_file()

    with zipfile.ZipFile(archive_zip) as zf:
        names = zf.namelist()
        assert "delivery/approved-homepage.html" in names
        assert "delivery/ghl-ready.html" in names
        assert "assets/optimized/hero_dog.jpg" in names
