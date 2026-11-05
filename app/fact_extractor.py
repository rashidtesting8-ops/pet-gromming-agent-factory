"""Deterministic, provenance-verified business fact extractor with prompt-injection defense.

Parses business name, phone, address, hours, grooming services, pricing tiers,
and cancellation policies from crawled pages and raw HTML snapshots. Every claim
must record `source_url`, `source_text_snippet`, and `is_verified` (boolean).
If a price or claim cannot be mapped to an exact substring in the crawled HTML,
it is marked with `status="needs_review"` and `is_verified=False` (0).
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.collector import collect_page_text, sanitize_prompt_injection, slugify

FactStatus = Literal["verified", "needs_review", "expired"]

PHONE_RE = re.compile(
    r"(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}\b"
)
ADDRESS_RE = re.compile(
    r"(?:Address\s*:\s*)?(\d{1,6}\s+[A-Za-z0-9.\s]+,\s*[A-Za-z.\s]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)",
    re.I,
)
HOURS_RE = re.compile(
    r"(?:Hours\s*:\s*)?((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[A-Za-z\s,-]*\d{1,2}(?::\d{2})?\s*(?:AM|PM)\s*[-–to]+\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM))",
    re.I,
)
PRICE_LINE_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9\s&/()-]{2,60}?)\s*[-–:]+\s*(\$\d+(?:\.\d{2})?)\b"
)
PRICE_TOKEN_RE = re.compile(r"\$\d+(?:\.\d{2})?")
POLICY_RE = re.compile(
    r"(?:Cancellation\s+Policy\s*:\s*)?([^.\n]*(?:cancellation|notice|no-show|reschedul)[^.\n]*\.?)",
    re.I,
)
SERVICE_KEYWORDS = (
    "groom",
    "bath",
    "brush",
    "trim",
    "nail",
    "deshed",
    "de-shed",
    "puppy",
    "scissoring",
    "styling",
    "sanitary",
    "ear cleaning",
    "teeth",
)


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


class CandidateClaim(BaseModel):
    """Input candidate claim to verify against crawled HTML snapshots."""

    model_config = ConfigDict(extra="forbid")

    category: str
    claim_key: str
    claim_value: str
    source_url: str
    source_text_snippet: str


class ExtractedFact(BaseModel):
    """Pydantic v2 schema for a single provenance-checked business fact."""

    model_config = ConfigDict(extra="forbid")

    fact_id: str
    project_id: str
    category: str
    claim_key: str
    claim_value: str
    source_url: str
    source_text_snippet: str
    is_verified: bool = False
    status: FactStatus = "needs_review"
    last_checked_at: datetime = Field(default_factory=_utc_now)

    @field_validator(
        "fact_id",
        "project_id",
        "category",
        "claim_key",
        "claim_value",
        "source_url",
        "source_text_snippet",
    )
    @classmethod
    def _validate_non_blank(cls, v: str, info: Any) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError(f"{info.field_name} must not be empty")
        return cleaned

    @field_validator("last_checked_at")
    @classmethod
    def _validate_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("last_checked_at must be timezone-aware")
        return v


class BusinessFactsReport(BaseModel):
    """Pydantic v2 schema persisted to projects/<business-id>/research/business-facts.json."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    extracted_at: datetime = Field(default_factory=_utc_now)
    facts: list[ExtractedFact]
    prompt_injection_warnings: list[str] = Field(default_factory=list)


def verify_claim_against_html(
    *,
    claim_value: str,
    source_text_snippet: str,
    sanitized_text: str,
    raw_html_unescaped: str,
) -> bool:
    """Return True only if source_text_snippet and claim_value map to exact substrings."""
    snippet = source_text_snippet.strip()
    val = claim_value.strip()
    if not snippet or not val:
        return False

    _, snippet_injections = sanitize_prompt_injection(snippet)
    _, val_injections = sanitize_prompt_injection(val)
    if snippet_injections or val_injections:
        return False

    if val not in snippet:
        return False

    return snippet in sanitized_text or snippet in raw_html_unescaped


def _make_fact(
    *,
    project_id: str,
    category: str,
    claim_key: str,
    claim_value: str,
    source_url: str,
    source_text_snippet: str,
    sanitized_text: str,
    raw_html_unescaped: str,
) -> ExtractedFact:
    verified = verify_claim_against_html(
        claim_value=claim_value,
        source_text_snippet=source_text_snippet,
        sanitized_text=sanitized_text,
        raw_html_unescaped=raw_html_unescaped,
    )
    digest = hashlib.sha256(
        f"{project_id}:{category}:{claim_key}:{claim_value}:{source_url}".encode()
    ).hexdigest()[:12]
    return ExtractedFact(
        fact_id=f"fact-{digest}",
        project_id=project_id,
        category=category,
        claim_key=claim_key,
        claim_value=claim_value.strip(),
        source_url=source_url,
        source_text_snippet=source_text_snippet.strip(),
        is_verified=verified,
        status="verified" if verified else "needs_review",
    )


def _extract_candidates_from_page(
    *,
    url: str,
    title: str,
    sanitized_text: str,
) -> list[CandidateClaim]:
    candidates: list[CandidateClaim] = []
    lines = [line.strip() for line in sanitized_text.splitlines() if line.strip()]

    # 1. Business Name
    if title.strip():
        clean_title, hits = sanitize_prompt_injection(title.strip())
        if clean_title and not hits:
            for line in lines:
                if clean_title in line:
                    candidates.append(
                        CandidateClaim(
                            category="business_name",
                            claim_key="business_name",
                            claim_value=clean_title,
                            source_url=url,
                            source_text_snippet=line,
                        )
                    )
                    break

    for line in lines:
        # 2. Phone
        phone_match = PHONE_RE.search(line)
        if phone_match and not any(c.claim_key == "phone" for c in candidates):
            candidates.append(
                CandidateClaim(
                    category="phone",
                    claim_key="phone",
                    claim_value=phone_match.group(0).strip(),
                    source_url=url,
                    source_text_snippet=line,
                )
            )

        # 3. Address
        addr_match = ADDRESS_RE.search(line)
        if addr_match and not any(c.claim_key == "address" for c in candidates):
            candidates.append(
                CandidateClaim(
                    category="address",
                    claim_key="address",
                    claim_value=addr_match.group(1).strip(),
                    source_url=url,
                    source_text_snippet=line,
                )
            )

        # 4. Hours
        hours_match = HOURS_RE.search(line)
        if hours_match and not any(c.claim_key == "hours" for c in candidates):
            candidates.append(
                CandidateClaim(
                    category="hours",
                    claim_key="hours",
                    claim_value=hours_match.group(1).strip(),
                    source_url=url,
                    source_text_snippet=line,
                )
            )

        # 5. Services & Pricing Tiers
        price_line = PRICE_LINE_RE.match(line)
        if price_line:
            svc_name = price_line.group(1).strip()
            price_val = price_line.group(2).strip()
            svc_slug = slugify(svc_name).replace("-", "_")
            candidates.append(
                CandidateClaim(
                    category="services",
                    claim_key=f"service_{svc_slug}",
                    claim_value=svc_name,
                    source_url=url,
                    source_text_snippet=line,
                )
            )
            candidates.append(
                CandidateClaim(
                    category="pricing",
                    claim_key=f"price_{svc_slug}",
                    claim_value=f"{svc_name}: {price_val}" if price_val not in line else price_val,
                    source_url=url,
                    source_text_snippet=line,
                )
            )
        elif any(kw in line.lower() for kw in SERVICE_KEYWORDS):
            price_tok = PRICE_TOKEN_RE.search(line)
            if price_tok:
                svc_slug = slugify(line[:32]).replace("-", "_")
                candidates.append(
                    CandidateClaim(
                        category="pricing",
                        claim_key=f"price_{svc_slug}",
                        claim_value=price_tok.group(0),
                        source_url=url,
                        source_text_snippet=line,
                    )
                )

        # 6. Cancellation Policy
        policy_match = POLICY_RE.search(line)
        if policy_match and not any(c.claim_key == "cancellation_policy" for c in candidates):
            candidates.append(
                CandidateClaim(
                    category="cancellation_policy",
                    claim_key="cancellation_policy",
                    claim_value=policy_match.group(1).strip(),
                    source_url=url,
                    source_text_snippet=line,
                )
            )

    return candidates


def extract_business_facts(
    project_folder: str | Path,
    *,
    candidate_claims: Sequence[CandidateClaim] | None = None,
) -> BusinessFactsReport:
    """Extract and verify business facts from crawled pages and save business-facts.json."""
    project_root = Path(project_folder).resolve()
    project_id = project_root.name
    pages_path = project_root / "research" / "pages.json"
    if not pages_path.is_file():
        raise ValueError(f"Missing crawled pages manifest: {pages_path}")

    pages: list[dict[str, Any]] = json.loads(pages_path.read_text(encoding="utf-8"))
    page_lookup: dict[str, tuple[str, str]] = {}
    injection_warnings: list[str] = []
    discovered_candidates: list[CandidateClaim] = []

    for page in pages:
        url = str(page.get("url", ""))
        sha = str(page.get("sha256", ""))
        title = str(page.get("title", ""))
        snap_path = project_root / "research" / "snapshots" / f"{sha}.html"

        raw_html = ""
        if snap_path.is_file():
            raw_html = snap_path.read_text(encoding="utf-8", errors="replace")
            soup = BeautifulSoup(raw_html, "html.parser")
            collected = collect_page_text(soup, url)
            sanitized_text = str(collected["text"])
            injection_warnings.extend(collected.get("prompt_injection_hits", []))
        else:
            raw_text = str(page.get("text", ""))
            sanitized_text, hits = sanitize_prompt_injection(raw_text)
            injection_warnings.extend(hits)

        unescaped_html, _ = sanitize_prompt_injection(html.unescape(raw_html))
        page_lookup[url] = (sanitized_text, unescaped_html)
        discovered_candidates.extend(
            _extract_candidates_from_page(
                url=url,
                title=title,
                sanitized_text=sanitized_text,
            )
        )

    if candidate_claims:
        discovered_candidates.extend(candidate_claims)

    facts: list[ExtractedFact] = []
    for cand in discovered_candidates:
        sanitized_text, unescaped_html = page_lookup.get(cand.source_url, ("", ""))
        fact = _make_fact(
            project_id=project_id,
            category=cand.category,
            claim_key=cand.claim_key,
            claim_value=cand.claim_value,
            source_url=cand.source_url,
            source_text_snippet=cand.source_text_snippet,
            sanitized_text=sanitized_text,
            raw_html_unescaped=unescaped_html,
        )
        facts.append(fact)

    report = BusinessFactsReport(
        project_id=project_id,
        facts=facts,
        prompt_injection_warnings=sorted(set(injection_warnings)),
    )
    out_path = project_root / "research" / "business-facts.json"
    _atomic_write_text(out_path, report.model_dump_json(indent=2))
    return report

