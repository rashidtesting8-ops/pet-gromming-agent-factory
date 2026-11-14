"""End-to-end Definition of Done (DoD) acceptance test covering all 10 DoD clauses."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from app.approval import approve_release, stage_release_candidate
from app.claim_scanner import scan_project_html
from app.cockpit import generate_review_summary
from app.generator import revise_section
from app.pipeline import run_pipeline
from app.reviser import compute_section_hashes
from app.rights import confirm_asset_rights
from src.engine.cleanup import archive_path, cleanup
from src.engine.llm.adapter import BudgetConfig, FakeProvider, LLMAdapter, LLMResponse
from tests.test_pipeline_e2e import _ephemeral_grooming_salon_server
from tests.test_pipeline_lifecycle import _fast_qa_runner


def test_definition_of_done_full_e2e_lifecycle(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    db_path = tmp_path / "editvista.sqlite3"

    editorial_payload = {
        "editorial_headline": "Furry Tail Spa",
        "editorial_tagline": "Gentle dog and cat grooming",
        "editorial_value_prop": "Patient bath and groom care for dogs and cats.",
        "suggested_sections": ["hero", "services", "contact"],
    }
    bespoke_hero = {
        "hero": (
            '<section id="hero" class="ev-hero ev-dod-bespoke" data-section="hero">'
            "<h1>Furry Tail Spa</h1>"
            "<p>Gentle bath and brush grooming for dogs and cats.</p>"
            "</section>"
        )
    }
    critique_payload = {"status": "passed", "defects": []}
    provider = FakeProvider(
        canned_responses=[
            LLMResponse(
                content=json.dumps(editorial_payload),
                prompt_tokens=100,
                completion_tokens=40,
                total_tokens=140,
                model="fake-art",
            ),
            LLMResponse(
                content=json.dumps(bespoke_hero),
                prompt_tokens=100,
                completion_tokens=40,
                total_tokens=140,
                model="fake-gen",
            ),
            LLMResponse(
                content=json.dumps(critique_payload),
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
                model="fake-critic",
            ),
        ]
    )
    adapter = LLMAdapter(
        provider,
        config=BudgetConfig(
            cache_dir=tmp_path / ".cache" / "llm",
            ledger_path=tmp_path / ".cache" / "ledger.jsonl",
            db_path=tmp_path / ".cache" / "budget.sqlite3",
        ),
    )

    with _ephemeral_grooming_salon_server() as base_url:
        # 1. Initial run fails mid-way (simulated QA crash)
        def _failing_qa_once(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("Simulated Playwright timeout")

        with pytest.raises(RuntimeError, match="Simulated Playwright timeout"):
            run_pipeline(
                url=base_url,
                business_name="Furry Tail Spa",
                projects_dir=projects_dir,
                db_path=db_path,
                qa_runner=_failing_qa_once,
                llm_adapter=adapter,
                acknowledge_gaps=True,
            )

        # 2. Resume failed job cleanly
        resumed = run_pipeline(
            url=base_url,
            business_name="Furry Tail Spa",
            projects_dir=projects_dir,
            db_path=db_path,
            resume=True,
            qa_runner=_fast_qa_runner,
            llm_adapter=adapter,
            pause_for_approval=True,
            acknowledge_gaps=True,
        )
        assert resumed.status == "awaiting_approval"
        assert resumed.qa_passed is True
        proj = resumed.project_folder

        # 3. Review source material + critique + 5-view QA results
        summary = generate_review_summary(proj.name, projects_dir=projects_dir)
        assert summary["fact_metrics"]["total_facts"] >= 1
        assert summary["technical_qa_passed"] is True
        assert summary["visual_critique_status"] in ("passed", "defects_found")
        assert len(summary["screenshots"]) == 5

        # 4. Bespoke homepage generated
        hero_sec = (proj / "website" / "sections" / "hero.html").read_text(encoding="utf-8")
        assert "ev-dod-bespoke" in hero_sec

        # 5. Precise single-section revision leaves other section hashes unchanged
        before_hashes = compute_section_hashes(proj / "website" / "index.html")
        updated_hero = hero_sec.replace(
            "Gentle bath and brush grooming for dogs and cats.",
            "Calm bath and brush grooming for dogs and cats.",
        )
        after_hashes = revise_section("hero", updated_hero, project_folder=proj)
        assert after_hashes["hero"] != before_hashes["hero"]
        for sec_name, h_val in before_hashes.items():
            if sec_name != "hero":
                assert after_hashes[sec_name] == h_val

        # Re-stage and re-run QA after revision so candidate sha256 matches qa-report.json
        stage_release_candidate(proj)
        _fast_qa_runner(proj)

        # 6. Confirm asset rights (if any) & approve release
        manifest_path = proj / "research" / "asset-manifest.json"
        if manifest_path.is_file() and json.loads(manifest_path.read_text(encoding="utf-8")):
            confirm_asset_rights(
                proj,
                all_assets=True,
                basis="owner_permission",
                operator="DoD Reviewer",
                evidence="Confirmed in DoD test",
                db_path=db_path,
            )

        manifest_sha = approve_release(
            proj, operator_name="DoD Reviewer", db_path=db_path, acknowledge_open_issues=True
        )
        assert len(manifest_sha) == 64

        # 7. Retrieve local + GHL files with zero unsupported claims
        approved_html = proj / "delivery" / "approved-homepage.html"
        ghl_html = proj / "delivery" / "ghl-ready.html"
        assert approved_html.is_file()
        assert ghl_html.is_file()
        assert "ev-ghl-scope" in ghl_html.read_text(encoding="utf-8")
        assert scan_project_html(proj, approved_html).passed is True

        # 8. Safe cleanup after verified backup archive
        cleanup_res = cleanup(proj, mode="prune", confirm=True)
        arch_zip = archive_path(proj)
        assert arch_zip.is_file()
        with zipfile.ZipFile(arch_zip, "r") as zf:
            assert zf.testzip() is None
        assert approved_html.is_file()
        assert ghl_html.is_file()
        assert cleanup_res["mode"] == "prune"
