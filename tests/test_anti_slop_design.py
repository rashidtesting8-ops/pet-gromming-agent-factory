"""TDD tests verifying the anti-AI-slop design & copy overhaul."""

from __future__ import annotations

import json
from pathlib import Path

from app.art_director import generate_art_direction
from app.generator import generate_website
from PIL import Image


def _write_img(path: Path, color: tuple[int, int, int] = (27, 54, 93)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (640, 480), color=color).save(path, format="JPEG", quality=90)


def _seed_salon(project_root: Path) -> None:
    (project_root / "research").mkdir(parents=True, exist_ok=True)
    (project_root / "design").mkdir(parents=True, exist_ok=True)
    _write_img(project_root / "assets" / "website" / "logo.jpg", (27, 54, 93))
    _write_img(project_root / "assets" / "optimized" / "hero_01.webp", (45, 75, 110))
    _write_img(project_root / "assets" / "optimized" / "gal_01.webp", (150, 120, 90))
    _write_img(project_root / "assets" / "optimized" / "gal_02.webp", (100, 130, 120))
    _write_img(project_root / "assets" / "optimized" / "gal_03.webp", (80, 100, 130))

    (project_root / "research" / "business-facts.json").write_text(
        json.dumps(
            {
                "project_id": project_root.name,
                "facts": [
                    {
                        "category": "business_name",
                        "claim_key": "name",
                        "claim_value": "Bark & Brush",
                        "is_verified": True,
                        "status": "verified",
                    },
                    {
                        "category": "phone",
                        "claim_key": "phone",
                        "claim_value": "(512) 555-0140",
                        "is_verified": True,
                        "status": "verified",
                    },
                    {
                        "category": "services",
                        "claim_key": "svc_bath",
                        "claim_value": "Full Bath & Brush",
                        "is_verified": True,
                        "status": "verified",
                    },
                    {
                        "category": "pricing",
                        "claim_key": "price_bath",
                        "claim_value": "$65",
                        "is_verified": True,
                        "status": "verified",
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (project_root / "design" / "image-selection.json").write_text(
        json.dumps(
            {
                "project_id": project_root.name,
                "hero_image": {
                    "filename": "hero_01.webp",
                    "relative_path": "assets/optimized/hero_01.webp",
                    "object_position": "50% 28%",
                },
                "grooming_gallery": [
                    {
                        "filename": "gal_01.webp",
                        "relative_path": "assets/optimized/gal_01.webp",
                        "object_position": "50% 35%",
                    },
                    {
                        "filename": "gal_02.webp",
                        "relative_path": "assets/optimized/gal_02.webp",
                        "object_position": "50% 40%",
                    },
                    {
                        "filename": "gal_03.webp",
                        "relative_path": "assets/optimized/gal_03.webp",
                        "object_position": "50% 30%",
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_no_ai_slop_cliches_or_engine_branding_in_output(tmp_path: Path) -> None:
    proj = tmp_path / "bark-and-brush"
    _seed_salon(proj)
    generate_art_direction(proj)
    bundle = generate_website(proj)
    html_text = bundle.index_html_path.read_text(encoding="utf-8")

    slop_phrases = (
        "Verified by EditVista",
        "Luxury Pet Grooming Engine",
        "Direct Concierge Line",
        "Reservations & Concierge",
        "Hours & Concierge",
        "Editorial Lookbook",
        "Curated Grooming Menu",
        "tailored to your companion",
        "cared for by our stylists",
        "Gallery Photo 1",
    )
    for phrase in slop_phrases:
        assert phrase not in html_text, f"Found AI-slop phrase in HTML: {phrase!r}"


def test_editorial_layout_avoids_uniform_box_in_box_and_has_real_bento_and_archetype_css(
    tmp_path: Path,
) -> None:
    proj = tmp_path / "bark-and-brush"
    _seed_salon(proj)
    generate_art_direction(proj)
    bundle = generate_website(proj)
    css_text = bundle.css_path.read_text(encoding="utf-8")

    # Real asymmetric bento grid must span featured item across 2 columns on desktop
    assert ".ev-bento-item--featured" in css_text
    assert "grid-column: span 2" in css_text
    # Archetype-specific styling rules must exist in CSS (not identical across archetypes)
    assert '[data-archetype="mobile"]' in css_text
    assert '[data-archetype="salon"]' in css_text
    # Alternating full-bleed surface rhythm instead of every section being a shadowed rounded card
    assert ".ev-band--alt" in css_text or "data-surface=" in bundle.index_html_path.read_text(
        encoding="utf-8"
    )


def test_gallery_with_seven_plus_photos_passes_claim_scanner(tmp_path: Path) -> None:
    """7+ gallery cards must never emit sequential digits like '01 02 ... 07' that trip PHONE_RE."""
    from app.claim_scanner import scan_project_html

    proj = tmp_path / "seven-photos"
    _seed_salon(proj)
    sel_path = proj / "design" / "image-selection.json"
    sel_data = json.loads(sel_path.read_text(encoding="utf-8"))
    for idx in range(4, 9):
        fname = f"gal_{idx:02d}.webp"
        _write_img(proj / "assets" / "optimized" / fname, (90 + idx * 5, 110, 120))
        sel_data["grooming_gallery"].append(
            {
                "filename": fname,
                "relative_path": f"assets/optimized/{fname}",
                "object_position": "50% 35%",
            }
        )
    sel_path.write_text(json.dumps(sel_data, indent=2), encoding="utf-8")

    generate_art_direction(proj)
    bundle = generate_website(proj)
    report = scan_project_html(proj, bundle.index_html_path)
    assert report.passed, f"Unexpected claim violations: {report.violations}"
