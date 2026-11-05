from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from engine.contracts import Asset, Claim, StageInput, StageOutput, Warning


def test_valid_stage_input_and_output_pass() -> None:
    stage_in = StageInput(
        project_id="groomer-001",
        run_id="run-001",
        input_manifest_version="1.0",
        paths=["research/pages.json", "research/asset-manifest.json"],
    )
    assert stage_in.project_id == "groomer-001"
    assert stage_in.paths == ["research/pages.json", "research/asset-manifest.json"]

    warn = Warning(code="LOW_RES", message="Image width under 400px", path="assets/website/a.jpg")
    stage_out = StageOutput(
        status="ok",
        outputs=["research/business-facts.json"],
        warnings=[warn],
        errors=[],
        checksums={"research/business-facts.json": "a" * 64},
    )
    assert stage_out.status == "ok"
    assert len(stage_out.warnings) == 1


def test_valid_asset_and_rights_default_false() -> None:
    asset = Asset(
        asset_id="asset-001",
        source_url="https://example.com/images/dog.jpg",
        page_url="https://example.com/gallery",
        local_path="assets/website/dog-abcdef123456.jpg",
        sha256="a" * 64,
        width=1200,
        height=800,
        mime="image/jpeg",
        captured_at=datetime(2026, 11, 5, 8, 0, 0, tzinfo=UTC),
        category="gallery",
        notes="Clear full-body golden retriever groom",
    )
    assert asset.rights_confirmed_for_preview is False
    assert asset.width == 1200
    assert asset.height == 800


def test_asset_naive_datetime_fails() -> None:
    with pytest.raises(ValidationError):
        Asset(
            asset_id="asset-002",
            source_url="https://example.com/images/dog.jpg",
            page_url="https://example.com/gallery",
            local_path="assets/website/dog-abcdef123456.jpg",
            sha256="b" * 64,
            width=800,
            height=600,
            mime="image/jpeg",
            captured_at=datetime(2026, 11, 5, 8, 0, 0),  # naive datetime
            category="gallery",
            notes=None,
        )


def test_valid_claim_passes() -> None:
    claim = Claim(
        field="service_price",
        value="Full Groom from £45",
        source_url="https://example.com/prices",
        source_text="Full Groom package starts from £45 for small breeds.",
        snapshot_sha256="c" * 64,
        verified=True,
        status="verified",
        last_checked_at=datetime(2026, 11, 5, 8, 30, 0, tzinfo=UTC),
    )
    assert claim.status == "verified"
    assert claim.verified is True
    assert not Path(claim.source_text).is_absolute()


@pytest.mark.parametrize("bad_source_text", [None, "", "   "])
def test_claim_missing_or_blank_source_text_fails(bad_source_text: str | None) -> None:
    with pytest.raises(ValidationError):
        Claim(
            field="discount",
            value="20% off first groom",
            source_url="https://example.com/",
            source_text=bad_source_text,  # type: ignore[arg-type]
            snapshot_sha256="d" * 64,
            verified=False,
            status="needs_review",
            last_checked_at=datetime(2026, 11, 5, 8, 30, 0, tzinfo=UTC),
        )


def test_claim_missing_source_text_kwarg_fails() -> None:
    with pytest.raises(ValidationError):
        Claim.model_validate(
            {
                "field": "business_name",
                "value": "Pup Salon",
                "source_url": "https://example.com/",
                "snapshot_sha256": "e" * 64,
                "verified": True,
                "status": "verified",
                "last_checked_at": "2026-11-05T08:30:00Z",
            }
        )


def test_claim_naive_datetime_fails() -> None:
    with pytest.raises(ValidationError):
        Claim(
            field="opening_hours",
            value="Mon-Sat 9am-5pm",
            source_url="https://example.com/contact",
            source_text="Open Monday to Saturday, 9am to 5pm.",
            snapshot_sha256="f" * 64,
            verified=True,
            status="verified",
            last_checked_at=datetime(2026, 11, 5, 8, 30, 0),  # naive datetime
        )


def test_claim_invalid_status_fails() -> None:
    with pytest.raises(ValidationError):
        Claim(
            field="opening_hours",
            value="Mon-Sat 9am-5pm",
            source_url="https://example.com/contact",
            source_text="Open Monday to Saturday, 9am to 5pm.",
            snapshot_sha256="f" * 64,
            verified=False,
            status="invented",  # type: ignore[arg-type]
            last_checked_at=datetime(2026, 11, 5, 8, 30, 0, tzinfo=UTC),
        )

