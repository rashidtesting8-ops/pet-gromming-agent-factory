"""Tests for importing Instagram/Facebook 'Download your information' exports."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from engine.import_meta_export import import_meta_export


def _make_png_bytes(color: tuple[int, int, int] = (40, 120, 200)) -> bytes:
    im = Image.new("RGB", (48, 32), color=color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_import_instagram_folder_export_and_unknown_fields_ignored(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "research").mkdir(parents=True)

    export_dir = tmp_path / "ig_export"
    media_dir = export_dir / "media" / "posts" / "202605"
    content_dir = export_dir / "your_instagram_activity" / "content"
    media_dir.mkdir(parents=True)
    content_dir.mkdir(parents=True)

    img1 = _make_png_bytes((10, 20, 30))
    img2 = _make_png_bytes((40, 50, 60))
    (media_dir / "poodle_cut.png").write_bytes(img1)
    (media_dir / "bath_time.png").write_bytes(img2)

    # Real timestamps: 2026-05-10T15:30:00Z (1778427000) and 2026-05-12T10:00:00Z (1778580000)
    ts1 = int(datetime(2026, 5, 10, 15, 30, 0, tzinfo=UTC).timestamp())
    ts2 = int(datetime(2026, 5, 12, 10, 0, 0, tzinfo=UTC).timestamp())

    posts_v1 = [
        {
            "title": "Fresh poodle cut!",
            "creation_timestamp": ts1,
            "unknown_future_meta_field": {"nested": [1, 2, 3]},
            "media": [
                {
                    "uri": "media/posts/202605/poodle_cut.png",
                    "creation_timestamp": ts1,
                    "title": "Spa day for Bella",
                    "media_metadata": {"camera_info": {"has_metadata": False}},
                }
            ],
        }
    ]
    reels_v2 = {
        "ig_reels_media": [
            {
                "media": [
                    {
                        "uri": "media/posts/202605/bath_time.png",
                        "creation_timestamp": ts2,
                        "title": "Bubble bath reel",
                        "unexpected_flag": True,
                    }
                ]
            }
        ],
        "schema_version": "99.0-unknown",
    }

    (content_dir / "posts_1.json").write_text(json.dumps(posts_v1), encoding="utf-8")
    (content_dir / "reels.json").write_text(json.dumps(reels_v2), encoding="utf-8")
    # Include a broken JSON file and an entry without a timestamp to verify defensive logging
    (content_dir / "broken.json").write_text("{not-valid-json", encoding="utf-8")
    (content_dir / "unverified_post.json").write_text(
        json.dumps([{"media": [{"uri": "media/posts/202605/poodle_cut.png"}]}]),
        encoding="utf-8",
    )

    result = import_meta_export(
        project_folder=project,
        export_path=export_dir,
        platform="instagram",
    )

    assert result["status"] == "imported_needs_review"
    assert result["files_added"] == 2
    assert len(result["unparsed"]) >= 2  # broken.json + missing timestamp entry

    asset_manifest = json.loads(
        (project / "research" / "asset-manifest.json").read_text(encoding="utf-8")
    )
    assert len(asset_manifest) == 2

    by_notes = {row["notes"]: row for row in asset_manifest}
    row1 = by_notes["Spa day for Bella"]
    assert row1["captured_at"] == "2026-05-10T15:30:00+00:00"
    assert row1["post_date"] == "2026-05-10T15:30:00+00:00"
    assert row1["post_date_verified"] is True
    assert row1["rights_confirmed_for_preview"] is False
    assert row1["width"] == 48
    assert row1["height"] == 32
    assert row1["mime"] == "image/png"
    assert (project / row1["local_path"]).exists()

    row2 = by_notes["Bubble bath reel"]
    assert row2["captured_at"] == "2026-05-12T10:00:00+00:00"
    assert row2["rights_confirmed_for_preview"] is False


def test_import_facebook_zip_export_and_deduplication(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "research").mkdir(parents=True)

    zip_path = tmp_path / "fb_export.zip"
    ts = int(datetime(2026, 4, 1, 9, 15, 0, tzinfo=UTC).timestamp())
    fb_posts = {
        "posts": [
            {
                "timestamp": ts,
                "data": [{"post": "Happy terrier after grooming"}],
                "attachments": [
                    {
                        "data": [
                            {
                                "media": {
                                    "uri": "posts/media/terrier.png",
                                    "creation_timestamp": ts,
                                    "description": "Happy terrier after grooming",
                                }
                            }
                        ]
                    }
                ],
            }
        ]
    }
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("your_activity_across_facebook/posts/your_posts_1.json", json.dumps(fb_posts))
        zf.writestr("posts/media/terrier.png", _make_png_bytes((90, 100, 110)))

    res1 = import_meta_export(project_folder=project, export_path=zip_path, platform="facebook")
    assert res1["status"] == "imported_needs_review"
    assert res1["files_added"] == 1

    # Re-running on same export is idempotent (deduplicated by sha256)
    res2 = import_meta_export(project_folder=project, export_path=zip_path, platform="facebook")
    assert res2["files_added"] == 0


def test_guards_against_path_traversal_zip_bomb_and_caps(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "research").mkdir(parents=True)

    outside_secret = tmp_path / "secret.png"
    outside_secret.write_bytes(_make_png_bytes((255, 0, 0)))

    zip_path = tmp_path / "malicious_export.zip"
    ts = int(datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC).timestamp())
    posts = [
        {
            "creation_timestamp": ts,
            "media": [
                {"uri": "../secret.png", "creation_timestamp": ts},
                {"uri": "media/valid1.png", "creation_timestamp": ts},
                {"uri": "media/valid2.png", "creation_timestamp": ts},
            ],
        }
    ]

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("content/posts_1.json", json.dumps(posts))
        # Path traversal entry in zip archive
        zf.writestr("../../escaped.png", _make_png_bytes((1, 1, 1)))
        zf.writestr("media/valid1.png", _make_png_bytes((2, 2, 2)))
        zf.writestr("media/valid2.png", _make_png_bytes((3, 3, 3)))
        # Oversized / high-ratio payload (2 MB of zeros)
        zf.writestr("media/huge_bomb.bin", b"\x00" * (2 * 1024 * 1024))

    res = import_meta_export(
        project_folder=project,
        export_path=zip_path,
        platform="instagram",
        max_files=1,
        max_item_bytes=500_000,
        max_total_bytes=1_000_000,
    )

    # Only 1 valid file imported due to max_files=1; traversal and oversized bomb blocked
    assert res["files_added"] == 1
    assert not (tmp_path / "escaped.png").exists()
    reasons = [item["reason"] for item in res["unparsed"]]
    assert any("traversal" in r or "unsafe_path" in r for r in reasons)
    assert any("too_large" in r or "zip_bomb" in r for r in reasons)

