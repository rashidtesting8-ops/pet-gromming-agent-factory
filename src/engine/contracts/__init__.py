"""Pydantic v2 contracts and atomic I/O helpers for the EditVista Pet Grooming Engine."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class StageStatus(StrEnum):
    OK = "ok"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageInput(BaseModel):
    """Standard input envelope for every pipeline stage (pass paths, never file bytes)."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=120)
    input_manifest_version: str = Field(default="1.0", min_length=1, max_length=32)
    paths: list[str] = Field(default_factory=list, max_length=256)

    @field_validator("paths")
    @classmethod
    def validate_safe_relative_paths(cls, values: list[str]) -> list[str]:
        for raw in values:
            norm = raw.replace("\\", "/")
            p = Path(norm)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError(f"Unsafe or non-relative stage path: {raw!r}")
        return values


class StageOutput(BaseModel):
    """Standard output envelope returned by every pipeline stage."""

    model_config = ConfigDict(extra="forbid")

    status: StageStatus
    outputs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    checksums: dict[str, str] = Field(default_factory=dict)

    @field_validator("checksums")
    @classmethod
    def validate_checksums(cls, mapping: dict[str, str]) -> dict[str, str]:
        for path_key, digest in mapping.items():
            if not SHA256_RE.match(digest):
                raise ValueError(f"Invalid SHA-256 checksum for {path_key!r}: {digest!r}")
        return mapping


class ClaimProvenance(BaseModel):
    """Factual claim with mandatory source attribution; unsupported claims become needs_review."""

    model_config = ConfigDict(extra="forbid")

    claim_text: str = Field(min_length=1)
    source_url: str | None = None
    source_text: str | None = None
    verified: bool = False
    last_checked_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> str:
        if self.verified and self.source_url and self.source_text:
            return "verified"
        return "needs_review"


class AssetProvenance(BaseModel):
    """Asset provenance contract enforcing sha256, timestamp, and default unconfirmed rights."""

    model_config = ConfigDict(extra="forbid")

    file: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    sha256: str
    captured_at: datetime
    rights_confirmed_for_preview: bool = False
    dimensions: tuple[int, int] | None = None
    mime: str | None = None

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not SHA256_RE.match(value):
            raise ValueError("sha256 must be a 64-character lowercase hex digest")
        return value


class CollectionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    social_lookback_days: int = Field(default=365, ge=1, le=366)
    website_max_pages: int = Field(default=25, ge=1, le=40)
    website_media_max_candidates: int = Field(default=80, ge=1, le=120)
    social_max_files_per_platform: int = Field(default=40, ge=1, le=80)
    record_provenance: bool = True
    require_human_asset_rights_review: bool = True


class ReviewPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    viewport_widths: list[int] = Field(default_factory=lambda: [1440, 1024, 768, 390, 360])
    human_approval_required: bool = True
    approval_status: str = "pending"


class DeliveryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_html: bool = True
    ghl_ready_snippet: bool = True
    public_hosting_required_for_local_review: bool = False
    cleanup_requires_verified_backup: bool = True


class BusinessInput(BaseModel):
    """Per-business intake configuration matching BUSINESS_INPUT_EXAMPLE.json."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=120)
    business_name: str | None = None
    website_url: str | None = None
    instagram_url: str | None = None
    facebook_url: str | None = None
    manual_asset_folder: str | None = None
    approved_brand_assets_folder: str | None = None
    preferred_contact_or_booking_url: str | None = None
    collection: CollectionPolicy = Field(default_factory=CollectionPolicy)
    review: ReviewPolicy = Field(default_factory=ReviewPolicy)
    delivery: DeliveryPolicy = Field(default_factory=DeliveryPolicy)


def atomic_write_bytes(path: str | Path, data: bytes) -> Path:
    """Write bytes atomically via a temporary file in the same directory and os.replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return target


def atomic_write_text(path: str | Path, content: str, encoding: str = "utf-8") -> Path:
    """Write UTF-8 text atomically via temp file + rename."""
    return atomic_write_bytes(path, content.encode(encoding))


def atomic_write_json(path: str | Path, payload: Any, *, ensure_ascii: bool = False) -> Path:
    """Serialize JSON and write atomically via temp file + rename."""
    serialized = json.dumps(payload, indent=2, ensure_ascii=ensure_ascii)
    return atomic_write_text(path, serialized, encoding="utf-8")
