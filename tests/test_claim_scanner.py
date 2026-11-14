"""Adversarial tests for the unsupported-claim scanner (zero-fabrication release gate)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from app.approval import ReleaseApprovalGateError, approve_release
from app.claim_scanner import scan_html_for_unsupported_claims
from tests.test_approval_archival import _scaffold_reviewable_project


def _fact(category: str, value: str, snippet: str = "", *, verified: bool = True) -> dict[str, Any]:
    return {
        "category": category,
        "claim_key": category,
        "claim_value": value,
        "source_text_snippet": snippet or value,
        "is_verified": verified,
        "status": "verified" if verified else "needs_review",
    }


def _page(body: str) -> str:
    return f"<!DOCTYPE html><html><head><title>t</title></head><body>{body}</body></html>"


def _kinds(html: str, facts: list[dict[str, Any]]) -> set[str]:
    return {v.kind for v in scan_html_for_unsupported_claims(html, facts).violations}


def test_invented_price_is_flagged_and_verified_price_passes() -> None:
    facts = [_fact("pricing", "$45", "Full bath from $45")]
    assert "money" in _kinds(_page("<p>Full groom $120</p>"), facts)
    assert scan_html_for_unsupported_claims(_page("<p>Full bath $45</p>"), facts).passed


def test_unverified_fact_never_supports_a_claim() -> None:
    facts = [_fact("pricing", "$45", verified=False)]
    assert "money" in _kinds(_page("<p>Bath $45</p>"), facts)


def test_invented_discount_percentage_is_flagged() -> None:
    assert "percent" in _kinds(_page("<p>Save 20% today</p>"), [])


def test_invented_phone_and_email_flagged_verified_pass_in_other_format() -> None:
    facts = [_fact("phone", "(512) 555-0190"), _fact("email", "hello@luxe.example")]
    assert "phone" in _kinds(_page("<p>Call 512 555 0199</p>"), facts)
    assert "email" in _kinds(_page("<p>mail me@evil.example</p>"), facts)
    ok = scan_html_for_unsupported_claims(
        _page("<p>Call 512-555-0190 or HELLO@luxe.example</p>"), facts
    )
    assert ok.passed, ok.violations


def test_credential_and_superlative_phrases_need_source_support() -> None:
    assert "credential" in _kinds(_page("<p>Award-winning groomers</p>"), [])
    assert "credential" in _kinds(_page("<p>Fully insured and certified</p>"), [])
    assert "credential" in _kinds(_page("<p>Cage-free hydro-bath suite</p>"), [])
    facts = [_fact("services", "Hydro-bath", "We offer a hydro-bath for every coat")]
    assert "credential" not in _kinds(_page("<p>Hydro-bath available</p>"), facts)


def test_experience_claims_flagged_but_copyright_year_is_not() -> None:
    assert "experience" in _kinds(_page("<p>Grooming since 1998</p>"), [])
    assert "experience" in _kinds(_page("<p>15 years of experience</p>"), [])
    assert scan_html_for_unsupported_claims(_page("<footer>&copy; 2026 Luxe</footer>"), []).passed


def test_scripts_styles_and_attributes_are_not_scanned_as_visible_text() -> None:
    html = _page(
        "<style>.x{content:'$999'}</style><script>var p='50%'</script>"
        '<a href="tel:5125550000">Call</a><p>Welcome</p>'
    )
    assert scan_html_for_unsupported_claims(html, []).passed


def test_approve_release_blocks_invented_claim_and_ack_flag_cannot_bypass(
    tmp_path: Path,
) -> None:
    projects_dir, project_root = _scaffold_reviewable_project(tmp_path, "claim-gate-salon")
    cand = project_root / "release-candidate" / "standalone.html"
    cand.write_text(
        cand.read_text(encoding="utf-8").replace(
            "Grooming Services</h2>", "Grooming Services</h2><p>Award-winning team</p>"
        ),
        encoding="utf-8",
    )
    qa_path = project_root / "qa" / "qa-report.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    qa["candidate_sha256"] = hashlib.sha256(cand.read_bytes()).hexdigest()
    qa_path.write_text(json.dumps(qa), encoding="utf-8")

    for ack in (False, True):
        with pytest.raises(ReleaseApprovalGateError, match="unsupported"):
            approve_release(
                "claim-gate-salon",
                version="v1",
                operator_name="Reviewer",
                notes="try",
                projects_dir=projects_dir,
                acknowledge_open_issues=ack,
            )
    assert not (project_root / "delivery").exists()
