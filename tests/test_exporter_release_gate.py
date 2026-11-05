"""Tests for the exporter release gate enforcing rights_confirmed_for_preview=True."""

from __future__ import annotations

import json
from pathlib import Path

from engine.exporter import check_used_asset_rights, export_release


def _setup_project(tmp_path: Path, *, instagram_rights: bool, website_rights: bool = True) -> Path:
    project = tmp_path / "salon"
    for sub in (
        "assets/website",
        "assets/instagram",
        "assets/optimized",
        "research",
        "website",
        "delivery",
    ):
        (project / sub).mkdir(parents=True, exist_ok=True)

    logo_path = project / "assets/website/logo-abc123.png"
    logo_path.write_bytes(b"fake-png-logo")
    ig_photo_path = project / "assets/instagram/instagram-dog999.jpg"
    ig_photo_path.write_bytes(b"fake-jpg-dog")
    unused_ig_path = project / "assets/instagram/instagram-unused000.jpg"
    unused_ig_path.write_bytes(b"fake-jpg-unused")

    website_manifest = [
        {
            "file": "assets/website/logo-abc123.png",
            "url": "https://salon.example/logo.png",
            "sha256": "a" * 64,
            "captured_at": "2026-06-01T10:00:00+00:00",
            "rights_confirmed_for_preview": website_rights,
        }
    ]
    social_manifest = [
        {
            "file": "assets/instagram/instagram-dog999.jpg",
            "optimized_file": "assets/optimized/instagram-dog999.jpg",
            "source_post_url": "https://www.instagram.com/p/dog999/",
            "original_post_url": "https://www.instagram.com/p/dog999/",
            "sha256": "b" * 64,
            "captured_at": "2026-06-02T12:00:00+00:00",
            "rights_confirmed_for_preview": instagram_rights,
        },
        {
            "file": "assets/instagram/instagram-unused000.jpg",
            "source_post_url": "https://www.instagram.com/p/unused000/",
            "sha256": "c" * 64,
            "captured_at": "2026-06-03T12:00:00+00:00",
            "rights_confirmed_for_preview": False,
        },
    ]

    (project / "research/asset-manifest.json").write_text(
        json.dumps(website_manifest, indent=2), encoding="utf-8"
    )
    (project / "research/social-media-manifest.json").write_text(
        json.dumps(social_manifest, indent=2), encoding="utf-8"
    )

    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Paws Salon</title>
  <style>
    .hero { background-image: url('../assets/instagram/instagram-dog999.jpg'); }
  </style>
</head>
<body>
  <header><img src="assets/website/logo-abc123.png" alt="Paws Salon Logo"></header>
  <main><section class="hero"><h1>Gentle Grooming</h1></section></main>
</body>
</html>
"""
    (project / "website/index.html").write_text(html, encoding="utf-8")
    return project


def test_exporter_refuses_when_used_asset_has_unconfirmed_rights(tmp_path: Path) -> None:
    project = _setup_project(tmp_path, instagram_rights=False, website_rights=True)

    result = export_release(project)

    assert result["status"] == "blocked_unconfirmed_rights"
    assert result["approved_built"] is False
    assert result["ghl_built"] is False
    assert not (project / "delivery/approved-homepage.html").exists()
    assert not (project / "delivery/ghl-ready.html").exists()

    offending = result["offending_assets"]
    assert len(offending) == 1
    assert offending[0]["file"] == "assets/instagram/instagram-dog999.jpg"
    assert offending[0]["rights_confirmed_for_preview"] is False
    assert offending[0]["sha256"] == "b" * 64


def test_exporter_builds_approved_and_ghl_when_all_used_assets_confirmed(tmp_path: Path) -> None:
    # Note: unused_ig_path still has rights_confirmed_for_preview=False, but is NOT used in HTML
    project = _setup_project(tmp_path, instagram_rights=True, website_rights=True)

    result = export_release(project)

    assert result["status"] == "exported"
    assert result["approved_built"] is True
    assert result["ghl_built"] is True
    assert result["offending_assets"] == []

    approved_path = project / "delivery/approved-homepage.html"
    ghl_path = project / "delivery/ghl-ready.html"
    retained_path = project / "delivery/retained-assets.json"
    assert approved_path.exists()
    assert ghl_path.exists()
    assert retained_path.exists()

    ghl_text = ghl_path.read_text(encoding="utf-8")
    assert "<html" not in ghl_text.lower()
    assert "<body" not in ghl_text.lower()
    assert "assets/website/logo-abc123.png" in ghl_text

    retained = json.loads(retained_path.read_text(encoding="utf-8"))
    assert retained["approved"] is True
    assert sorted(retained["assets"]) == [
        "assets/instagram/instagram-dog999.jpg",
        "assets/website/logo-abc123.png",
    ]


def test_exporter_refuses_when_used_asset_is_missing_from_manifests(tmp_path: Path) -> None:
    project = _setup_project(tmp_path, instagram_rights=True, website_rights=True)
    # Add an unindexed image to HTML
    (project / "assets/website/mystery.png").write_bytes(b"mystery")
    (project / "website/index.html").write_text(
        '<html><body><img src="assets/website/mystery.png"></body></html>',
        encoding="utf-8",
    )

    offending = check_used_asset_rights(project)
    assert len(offending) == 1
    assert offending[0]["file"] == "assets/website/mystery.png"
    assert offending[0]["rights_confirmed_for_preview"] is False

    res = export_release(project)
    assert res["status"] == "blocked_unconfirmed_rights"
    assert not (project / "delivery/approved-homepage.html").exists()

