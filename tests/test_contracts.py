import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from engine.contracts import (
    AssetProvenance,
    BusinessInput,
    ClaimProvenance,
    StageInput,
    StageOutput,
    StageStatus,
    atomic_write_json,
    atomic_write_text,
)


class ContractTests(unittest.TestCase):
    def test_stage_input_and_output_contract(self) -> None:
        stage_in = StageInput(
            project_id="pup-palace-001",
            run_id="run-20261104-01",
            input_manifest_version="1.0",
            paths=["research/pages.json", "research/asset-manifest.json"],
        )
        self.assertEqual(stage_in.project_id, "pup-palace-001")
        self.assertEqual(len(stage_in.paths), 2)

        stage_out = StageOutput(
            status=StageStatus.OK,
            outputs=["research/business-facts.json"],
            warnings=[],
            errors=[],
            checksums={"research/business-facts.json": "a" * 64},
        )
        self.assertEqual(stage_out.status, "ok")

    def test_stage_input_rejects_traversal_paths(self) -> None:
        with self.assertRaises(ValidationError):
            StageInput(
                project_id="pup-palace-001",
                run_id="run-01",
                input_manifest_version="1.0",
                paths=["../secret.txt"],
            )

    def test_claim_provenance_enforcement(self) -> None:
        now = datetime.now(UTC)
        claim = ClaimProvenance(
            claim_text="Full Groom starts at $65",
            source_url="https://example.com/services",
            source_text="Our Full Groom package starts at $65 for small dogs.",
            verified=True,
            last_checked_at=now,
        )
        self.assertEqual(claim.status, "verified")

        unverified = ClaimProvenance(
            claim_text="20% discount for first visit",
            source_url=None,
            source_text=None,
            verified=False,
            last_checked_at=now,
        )
        self.assertEqual(unverified.status, "needs_review")

    def test_asset_provenance_defaults_rights_false(self) -> None:
        now = datetime.now(UTC)
        asset = AssetProvenance(
            file="assets/website/logo-1234567890ab.png",
            source_url="https://example.com/logo.png",
            sha256="b" * 64,
            captured_at=now,
        )
        self.assertFalse(asset.rights_confirmed_for_preview)

        with self.assertRaises(ValidationError):
            AssetProvenance(
                file="assets/website/logo.png",
                source_url="https://example.com/logo.png",
                sha256="not-a-sha256",
                captured_at=now,
            )

    def test_business_input_example_validates(self) -> None:
        root_dir = Path(__file__).resolve().parent.parent
        example_path = root_dir / "examples" / "BUSINESS_INPUT_EXAMPLE.json"
        raw = json.loads(example_path.read_text(encoding="utf-8"))
        model = BusinessInput.model_validate(raw)
        self.assertEqual(model.project_id, "example-groomer-001")
        self.assertEqual(model.collection.social_lookback_days, 365)
        self.assertEqual(model.collection.website_max_pages, 25)
        self.assertEqual(model.collection.website_media_max_candidates, 80)
        self.assertEqual(model.collection.social_max_files_per_platform, 40)
        self.assertEqual(model.review.viewport_widths, [1440, 1024, 768, 390, 360])
        self.assertTrue(model.review.human_approval_required)

    def test_atomic_write_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            txt_file = root / "nested" / "note.txt"
            atomic_write_text(txt_file, "atomic content")
            self.assertEqual(txt_file.read_text(encoding="utf-8"), "atomic content")

            json_file = root / "nested" / "data.json"
            atomic_write_json(json_file, {"status": "ok", "count": 3})
            loaded = json.loads(json_file.read_text(encoding="utf-8"))
            self.assertEqual(loaded["status"], "ok")
            self.assertEqual(loaded["count"], 3)


if __name__ == "__main__":
    unittest.main()

