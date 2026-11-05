"""Pydantic v2 stage I/O, asset provenance, claim provenance, and warning contracts."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ClaimStatus = Literal["verified", "needs_review", "expired"]


class Warning(BaseModel):
    """Structured stage warning item."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(default="warning", min_length=1)
    message: str = Field(min_length=1)
    path: str | None = None


class StageInput(BaseModel):
    """Standard input contract for every stage (pass paths, never file bytes)."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    input_manifest_version: str = Field(default="1.0", min_length=1)
    paths: list[str] = Field(default_factory=list)

    @field_validator("paths")
    @classmethod
    def validate_paths(cls, values: list[str]) -> list[str]:
        for raw in values:
            norm = raw.replace("\\", "/")
            p = Path(norm)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError(f"Unsafe or non-relative path: {raw!r}")
        return values


class StageOutput(BaseModel):
    """Standard output contract returned by every stage."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1)
    outputs: list[str] = Field(default_factory=list)
    warnings: list[Warning | str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    checksums: dict[str, str] = Field(default_factory=dict)

    @field_validator("checksums")
    @classmethod
    def validate_checksums(cls, mapping: dict[str, str]) -> dict[str, str]:
        for key, digest in mapping.items():
            if not SHA256_RE.match(digest):
                raise ValueError(f"Invalid SHA-256 digest for {key!r}: {digest!r}")
        return mapping


class Asset(BaseModel):
    """Media asset provenance and metadata contract."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    page_url: str | None = None
    local_path: str = Field(min_length=1)
    sha256: str
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    mime: str = Field(min_length=1)
    captured_at: AwareDatetime
    rights_confirmed_for_preview: bool = False
    category: str = Field(default="uncertain", min_length=1)
    notes: str | list[str] | None = None

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not SHA256_RE.match(value):
            raise ValueError("sha256 must be a 64-character lowercase hex digest")
        return value


class Claim(BaseModel):
    """Business fact claim with mandatory source attribution and timezone-aware timestamp."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1)
    value: Any
    source_url: str = Field(min_length=1)
    source_text: str = Field(min_length=1)
    snapshot_sha256: str
    verified: bool
    status: ClaimStatus
    last_checked_at: AwareDatetime

    @field_validator("source_text")
    @classmethod
    def validate_non_blank_source_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_text must not be empty or whitespace-only")
        return value

    @field_validator("snapshot_sha256")
    @classmethod
    def validate_snapshot_sha256(cls, value: str) -> str:
        if not SHA256_RE.match(value):
            raise ValueError("snapshot_sha256 must be a 64-character lowercase hex digest")
        return value


__all__ = [
    "Asset",
    "Claim",
    "ClaimStatus",
    "StageInput",
    "StageOutput",
    "Warning",
]
