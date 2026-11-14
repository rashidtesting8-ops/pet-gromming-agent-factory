"""Unsupported-claim scanner: the zero-fabrication gate for generated HTML.

Every risky factual token in the *visible text* of a page (prices, discounts, phone numbers,
emails, experience claims, credential/superlative phrases) must be backed by a **verified**
fact in `research/business-facts.json`. Unverified (`needs_review`) facts never support a claim.
Text is DATA: nothing here executes or obeys page content.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field

MONEY_RE = re.compile(r"[£$€]\s?\d[\d,]*(?:\.\d{1,2})?")
PERCENT_RE = re.compile(r"\d{1,3}\s?%")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
EXPERIENCE_RE = re.compile(
    r"\bsince\s+(?:19|20)\d{2}\b|\b\d{1,2}\+?\s+years?\b", re.IGNORECASE
)

CREDENTIAL_PHRASES: tuple[str, ...] = (
    "award-winning",
    "award winning",
    "certified",
    "accredited",
    "fully insured",
    "insured",
    "licensed",
    "voted",
    "best in",
    "#1",
    "5-star",
    "five-star",
    "five star",
    "guaranteed",
    "money-back",
    "free consultation",
    "cage-free",
    "cage free",
    "hydro-bath",
    "hydro-massage",
    "hydrobath",
    "organic",
    "vet-approved",
    "veterinarian",
    "family-owned",
    "family owned",
)


class ClaimViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    text: str


class ClaimScanReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    violations: list[ClaimViolation] = Field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _compact(text: str) -> str:
    return re.sub(r"[\s,]", "", text.lower())


def visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return soup.get_text(" ")


def _support_corpus(facts: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for f in facts:
        if bool(f.get("is_verified", False)) and str(f.get("status", "verified")) == "verified":
            parts.append(str(f.get("claim_value", "")))
            parts.append(str(f.get("source_text_snippet", "")))
    return "\n".join(parts)


def scan_html_for_unsupported_claims(
    html: str, facts: list[dict[str, Any]]
) -> ClaimScanReport:
    text = visible_text(html)
    corpus = _support_corpus(facts)
    corpus_norm = _norm(corpus)
    corpus_compact = _compact(corpus)
    corpus_digits = _digits(corpus)
    violations: list[ClaimViolation] = []

    for m in MONEY_RE.finditer(text):
        if _compact(m.group(0)) not in corpus_compact:
            violations.append(ClaimViolation(kind="money", text=m.group(0)))
    for m in PERCENT_RE.finditer(text):
        if _compact(m.group(0)) not in corpus_compact:
            violations.append(ClaimViolation(kind="percent", text=m.group(0)))
    for m in PHONE_RE.finditer(text):
        digits = _digits(m.group(0))
        if len(digits) >= 10 and digits not in corpus_digits:
            violations.append(ClaimViolation(kind="phone", text=m.group(0).strip()))
    for m in EMAIL_RE.finditer(text):
        if m.group(0).lower() not in corpus.lower():
            violations.append(ClaimViolation(kind="email", text=m.group(0)))
    for m in EXPERIENCE_RE.finditer(text):
        if _norm(m.group(0)) not in corpus_norm:
            violations.append(ClaimViolation(kind="experience", text=m.group(0)))

    text_norm = _norm(text)
    for phrase in CREDENTIAL_PHRASES:
        pattern = re.compile(rf"(?<![\w#-]){re.escape(phrase)}(?![\w-])")
        if pattern.search(text_norm) and not pattern.search(corpus_norm):
            violations.append(ClaimViolation(kind="credential", text=phrase))

    seen: set[tuple[str, str]] = set()
    unique: list[ClaimViolation] = []
    for v in violations:
        key = (v.kind, v.text.lower())
        if key not in seen:
            seen.add(key)
            unique.append(v)
    return ClaimScanReport(passed=not unique, violations=unique)


def scan_project_html(project_root: Path, html_path: Path) -> ClaimScanReport:
    facts_path = project_root / "research" / "business-facts.json"
    facts: list[dict[str, Any]] = []
    if facts_path.is_file():
        payload = json.loads(facts_path.read_text(encoding="utf-8"))
        facts = list(payload.get("facts", [])) if isinstance(payload, dict) else []
    return scan_html_for_unsupported_claims(html_path.read_text(encoding="utf-8"), facts)

