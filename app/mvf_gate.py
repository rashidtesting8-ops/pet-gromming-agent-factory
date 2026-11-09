"""Minimum Viable Facts (MVF) gate and contact CTA enforcement.

Ensures no project reaches 'awaiting_approval' with too little verified information:
MVF requires:
1. Verified business name
2. At least one verified contact path (phone, booking URL, or email)
3. Verified service-type classification (animal types and business model)

If MVF is not met, writes qa/mvf-report.json with exact human action needed,
and blocks pipeline unless --acknowledge-gaps is provided.
When no verified contact path exists, omits CTAs to '#contact' from generated HTML.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.fact_extractor import ExtractedFact


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _atomic_write_text(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


class MVFReport(BaseModel):
    """Report detailing Minimum Viable Facts compliance and missing human actions."""

    model_config = ConfigDict(extra="allow")

    project_id: str
    passed: bool
    missing_items: list[str] = Field(default_factory=list)
    verified_items: list[str] = Field(default_factory=list)
    exact_human_action_needed: str
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
    cta_omitted: bool = False


def check_mvf(
    project_folder: Path | str,
    facts: Sequence[ExtractedFact] | Sequence[dict[str, Any]] | None = None,
) -> MVFReport:
    """Verify whether project meets Minimum Viable Facts (MVF) criteria."""
    project_root = Path(project_folder).resolve()
    project_id = project_root.name

    resolved_facts: list[dict[str, Any]] = []
    if facts is not None:
        for f in facts:
            if isinstance(f, ExtractedFact):
                resolved_facts.append(f.model_dump())
            elif isinstance(f, dict):
                resolved_facts.append(f)
    else:
        facts_path = project_root / "research" / "business-facts.json"
        if facts_path.is_file():
            try:
                data = json.loads(facts_path.read_text(encoding="utf-8"))
                resolved_facts = data.get("facts", [])
            except Exception:
                resolved_facts = []

    has_business_name = False
    has_contact_path = False
    has_service_type = False

    for fact in resolved_facts:
        category = str(fact.get("category", "")).lower()
        claim_key = str(fact.get("claim_key", "")).lower()
        claim_val = str(fact.get("claim_value", "")).strip()
        is_verified = bool(fact.get("is_verified", False))
        status = str(fact.get("status", "")).lower()

        if not (is_verified and status == "verified" and claim_val):
            continue

        if category == "business_name":
            has_business_name = True

        if category in ("phone", "booking_url", "email") or claim_key in (
            "phone",
            "booking_url",
            "email",
        ):
            has_contact_path = True

        if (
            category in ("business_model", "animal_types", "service_type")
            or claim_key in ("business_model", "animal_types", "service_type")
        ) and claim_val.lower() != "unknown":
            has_service_type = True

    verified_items: list[str] = []
    missing_items: list[str] = []

    if has_business_name:
        verified_items.append("business_name")
    else:
        missing_items.append("business_name")

    if has_contact_path:
        verified_items.append("contact_path")
    else:
        missing_items.append("contact_path")

    if has_service_type:
        verified_items.append("service_type")
    else:
        missing_items.append("service_type")

    passed = len(missing_items) == 0

    action_items: list[str] = []
    if not has_business_name:
        action_items.append(
            "Provide and verify the official business name in research/business-facts.json."
        )
    if not has_contact_path:
        action_items.append(
            "Provide at least one verified contact method (phone number, booking URL, "
            "or email address) in research/business-facts.json."
        )
    if not has_service_type:
        action_items.append(
            "Confirm the business model (salon/mobile/daycare) and animal types (dog/cat) "
            "in research/business-facts.json."
        )

    action_needed = (
        " ".join(action_items)
        if action_items
        else "All minimum viable facts verified; ready for approval."
    )

    return MVFReport(
        project_id=project_id,
        passed=passed,
        missing_items=missing_items,
        verified_items=verified_items,
        exact_human_action_needed=action_needed,
    )


def enforce_mvf_gate(
    project_folder: Path | str,
    *,
    acknowledge_gaps: bool = False,
    facts: Sequence[ExtractedFact] | Sequence[dict[str, Any]] | None = None,
) -> MVFReport:
    """Enforce the MVF gate, sanitize contact CTAs if needed, and write qa/mvf-report.json."""
    project_root = Path(project_folder).resolve()
    report = check_mvf(project_root, facts=facts)

    if acknowledge_gaps:
        report.acknowledged = True
        report.acknowledged_at = _utc_now()

    # Requirement 4: The generator must never emit a CTA to '#contact' when no verified
    # contact path exists. It omits the CTA and flags the gap instead.
    has_contact = "contact_path" in report.verified_items
    if not has_contact:
        cta_pattern = re.compile(
            r"<a\b[^>]*href=[\"']#contact[\"'][^>]*>.*?</a>",
            re.IGNORECASE | re.DOTALL,
        )

        for target_rel in (
            "website/index.html",
            "release-candidate/standalone.html",
            "release-candidate/approved-homepage.html",
        ):
            target_path = project_root / target_rel
            if target_path.is_file():
                content = target_path.read_text(encoding="utf-8")
                if "#contact" in content:
                    updated = cta_pattern.sub(
                        "<!-- CTA omitted: no verified contact path exists -->",
                        content,
                    )
                    if updated != content:
                        _atomic_write_text(target_path, updated)
                        report.cta_omitted = True

        if report.cta_omitted:
            report.warnings.append(
                "Generator omitted CTA to '#contact' because no verified contact path exists."
            )

    report_path = project_root / "qa" / "mvf-report.json"
    _atomic_write_text(report_path, report.model_dump_json(indent=2))
    return report

