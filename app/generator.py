"""Semantic HTML5/CSS/JS Website Generator for EditVista Pet Grooming Website Builder Engine.

Reads `design/creative-brief.json`, `design/brand.json`, `research/business-facts.json`,
and `design/image-selection.json` to synthesize semantic HTML5 (`<header>`, `<nav>`,
`<main>`, `<section>`, `<footer>`), responsive CSS with brand custom properties and
`clamp()` typography, and accessible vanilla JS (mobile navigation drawer + optional
before/after photo slider) with zero external CDN dependencies.
"""

from __future__ import annotations

import html
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field

from app.art_director import (
    FALLBACK_NAVY_HEX,
    FALLBACK_SOFT_SAGE_HEX,
    FALLBACK_WARM_AMBER_HEX,
    generate_art_direction,
)
from app.reviser import compute_section_hashes

MAX_SECTION_HTML_BYTES: int = 500_000
FORBIDDEN_URL_PREFIXES: tuple[str, ...] = ("http://", "https://", "//", "javascript:", "data:")


def validate_section_html(name: str, new_html: str) -> None:
    """Validate revised section HTML markup for security and structural integrity."""
    encoded = new_html.encode("utf-8")
    if len(encoded) > MAX_SECTION_HTML_BYTES:
        raise ValueError(
            f"Section HTML size exceeds cap of {MAX_SECTION_HTML_BYTES} bytes"
        )

    # Check for forbidden script tags (via regex first for quick catch)
    if re.search(r"<\s*script\b", new_html, re.IGNORECASE):
        raise ValueError("Script tags are forbidden in section HTML")

    soup = BeautifulSoup(new_html, "html.parser")

    # Double check soup for script tags
    if soup.find("script"):
        raise ValueError("Script tags are forbidden in section HTML")

    # Validate data-section attribute is present and matches the section name
    elements_with_section = soup.find_all(attrs={"data-section": True})
    if not elements_with_section:
        raise ValueError(
            f"Missing required data-section attribute (expected data-section='{name}')"
        )
    if not any(str(el.get("data-section")).strip() == name for el in elements_with_section):
        found_attrs = [el.get("data-section") for el in elements_with_section]
        raise ValueError(
            f"data-section attribute must match section name '{name}' (found: {found_attrs})"
        )

    # Validate no inline event handlers (attributes starting with 'on')
    # and no external URLs or unsafe schemes in attributes
    for el in soup.find_all(True):
        for attr_name, attr_val in el.attrs.items():
            if attr_name.lower().startswith("on"):
                raise ValueError(
                    f"Inline event handlers forbidden: found '{attr_name}' handler on <{el.name}>"
                )
            vals = attr_val if isinstance(attr_val, list) else [attr_val]
            for v in vals:
                v_str = str(v).strip().lower()
                if (
                    any(v_str.startswith(p) for p in FORBIDDEN_URL_PREFIXES)
                    or "http://" in v_str
                    or "https://" in v_str
                ):
                    raise ValueError(
                        "External URLs and unsafe schemes are forbidden in section HTML: "
                        f"{attr_name}='{v}'"
                    )

    # Check style tags for external URLs or unsafe schemes
    for style_tag in soup.find_all("style"):
        style_text = style_tag.get_text().lower()
        if any(p in style_text for p in ("http://", "https://", "//", "javascript:", "data:")):
            raise ValueError("External URLs and unsafe schemes are forbidden in section style tags")


def rebuild_index_from_sections(
    website_dir: str | Path,
    title: str | None = None,
) -> str:
    """Rebuild website/index.html strictly from per-section files under website/sections/."""
    wdir = Path(website_dir).resolve()
    sections_dir = wdir / "sections"
    if not sections_dir.is_dir():
        raise ValueError(f"Sections directory not found at {sections_dir}")

    section_files = list(sections_dir.glob("*.html"))
    sections_map: dict[str, str] = {}
    for p in section_files:
        sections_map[p.stem] = p.read_text(encoding="utf-8").strip()

    if "header" not in sections_map or "footer" not in sections_map:
        raise ValueError("Missing header or footer section file in sections directory")

    if not title:
        index_path = wdir / "index.html"
        if index_path.is_file():
            m = re.search(r"<title>(.*?)</title>", index_path.read_text(encoding="utf-8"), re.I)
            if m:
                title = m.group(1).strip()
        if not title:
            parent = wdir.parent
            for rel in ("design/creative-brief.json", "design/brand.json"):
                cand_file = parent / rel
                if cand_file.is_file():
                    try:
                        data = json.loads(cand_file.read_text(encoding="utf-8"))
                        if data.get("business_name"):
                            title = str(data["business_name"]).strip()
                            break
                    except Exception:
                        pass
        if not title:
            title = "Pet Grooming Salon"

    esc_title = html.escape(title)

    canonical_main_order = ["hero", "services", "gallery", "before-after", "contact"]
    main_section_names = [name for name in canonical_main_order if name in sections_map]
    other_sections = sorted([
        k for k in sections_map.keys()
        if k not in canonical_main_order and k not in ("header", "footer")
    ])
    all_main_names = main_section_names + other_sections
    main_body = "\n    ".join(sections_map[k] for k in all_main_names)

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc_title}</title>
  <link rel="stylesheet" href="css/styles.css">
</head>
<body>
  {sections_map['header']}
  <main id="top" class="ev-main">
    {main_body}
  </main>
  {sections_map['footer']}
  <script src="js/main.js"></script>
</body>
</html>
"""
    index_path = wdir / "index.html"
    _atomic_write_text(index_path, html_doc)
    return html_doc


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


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    cleaned = hex_color.strip().lstrip("#")
    if len(cleaned) != 6:
        return (27, 54, 93)
    return (int(cleaned[0:2], 16), int(cleaned[2:4], 16), int(cleaned[4:6], 16))


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    chans: list[float] = []
    for val in rgb:
        c = max(0, min(255, val)) / 255.0
        chans.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * chans[0] + 0.7152 * chans[1] + 0.0722 * chans[2]


def _contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    l1 = _relative_luminance(fg)
    l2 = _relative_luminance(bg)
    return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)


def _ensure_wcag_aa_on_white(hex_color: str) -> str:
    """Ensure color has >= 4.5:1 contrast ratio against white (#FFFFFF) for headings and CTAs."""
    rgb = _hex_to_rgb(hex_color)
    if _contrast_ratio(rgb, (255, 255, 255)) >= 4.7:
        return hex_color.upper()
    return FALLBACK_NAVY_HEX


class GeneratedWebsiteBundle(BaseModel):
    """Summary of generated website files under `projects/<business-id>/website/`."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    index_html_path: Path
    css_path: Path
    js_path: Path
    pricing_needs_review: bool
    has_before_after_slider: bool
    section_hashes_path: Path | None = None
    section_files: dict[str, Path] = Field(default_factory=dict)
    section_css_files: dict[str, Path] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=_utc_now)


def _find_before_after_pair(project_root: Path) -> tuple[str, str] | None:
    """Inspect optimized or website assets for an authentic before/after image pair."""
    before_rel: str | None = None
    after_rel: str | None = None

    for sub in ("assets/optimized", "assets/website"):
        folder = project_root / sub
        if not folder.is_dir():
            continue
        for f in sorted(folder.iterdir()):
            if not f.is_file():
                continue
            lower = f.name.lower()
            rel = f"../{sub}/{f.name}"
            if "before" in lower and before_rel is None:
                before_rel = rel
            elif "after" in lower and after_rel is None:
                after_rel = rel

    if before_rel and after_rel and before_rel != after_rel:
        return before_rel, after_rel
    return None


def _build_base_css(primary_hex: str, secondary_hex: str, accent_hex: str) -> str:
    safe_primary = _ensure_wcag_aa_on_white(primary_hex)
    return f""":root {{
  --ev-primary: {safe_primary};
  --ev-secondary: {secondary_hex};
  --ev-accent: {accent_hex};
  --ev-surface: #FFFFFF;
  --ev-bg: #F8FAFC;
  --ev-text: #0F172A;
  --ev-muted: #334155;
  --ev-border: #CBD5E1;
}}
* {{
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}}
body {{
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background-color: var(--ev-bg);
  color: var(--ev-text);
  line-height: 1.6;
  overflow-x: hidden;
}}
img {{
  max-width: 100%;
  height: auto;
  display: block;
}}
.cta, .btn {{
  display: inline-block;
  background-color: var(--ev-primary);
  color: #FFFFFF;
  text-decoration: none;
  font-weight: 700;
  padding: 0.75rem 1.35rem;
  border-radius: 8px;
  border: none;
  cursor: pointer;
}}
.ev-main {{
  max-width: 1200px;
  margin: 0 auto;
  padding: 1.5rem 1.25rem 3rem;
}}
"""


def _build_header_css() -> str:
    return """.ev-header {
  background-color: var(--ev-surface);
  border-bottom: 1px solid var(--ev-border);
  padding: 1rem 1.25rem;
}
.ev-nav {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}
.ev-brand-title {
  font-size: clamp(1.15rem, 2vw, 1.5rem);
  font-weight: 700;
  color: var(--ev-primary);
  text-decoration: none;
}
.ev-nav-toggle {
  background-color: var(--ev-primary);
  color: #FFFFFF;
  border: none;
  border-radius: 6px;
  padding: 0.5rem 0.85rem;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
}
.ev-nav-drawer {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  list-style: none;
  align-items: center;
}
.ev-nav-drawer[data-collapsed="true"] {
  display: none;
}
.ev-nav-link {
  color: var(--ev-primary);
  text-decoration: none;
  font-weight: 600;
}
"""


def _build_hero_css() -> str:
    return """.ev-hero {
  background-color: var(--ev-surface);
  border: 1px solid var(--ev-border);
  border-radius: 12px;
  padding: clamp(1.25rem, 3vw, 2.5rem);
  margin-bottom: 2rem;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
  gap: 1.5rem;
  align-items: center;
}
.ev-hero-title {
  font-size: clamp(1.75rem, 3.5vw, 2.75rem);
  color: var(--ev-primary);
  line-height: 1.2;
  margin-bottom: 0.75rem;
}
.ev-hero-subtitle {
  font-size: clamp(1rem, 1.5vw, 1.15rem);
  color: var(--ev-muted);
  margin-bottom: 1.25rem;
}
.ev-hero-media {
  width: 100%;
  border-radius: 10px;
  overflow: hidden;
  aspect-ratio: 16 / 10;
  background-color: #E2E8F0;
}
.ev-hero-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
"""


def _build_services_css() -> str:
    return """.ev-section {
  background-color: var(--ev-surface);
  border: 1px solid var(--ev-border);
  border-radius: 12px;
  padding: clamp(1.25rem, 2.5vw, 2rem);
  margin-bottom: 1.75rem;
}
.ev-section-title {
  font-size: clamp(1.35rem, 2.5vw, 2rem);
  color: var(--ev-primary);
  margin-bottom: 1rem;
}
.ev-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
  gap: 1.25rem;
}
.ev-card {
  background-color: var(--ev-bg);
  border: 1px solid var(--ev-border);
  border-radius: 8px;
  padding: 1rem;
}
.ev-card-title {
  font-size: 1.1rem;
  color: var(--ev-primary);
  margin-bottom: 0.4rem;
}
.ev-price-badge {
  display: inline-block;
  background-color: var(--ev-primary);
  color: #FFFFFF;
  font-weight: 700;
  padding: 0.2rem 0.6rem;
  border-radius: 4px;
  margin-top: 0.35rem;
}
"""


def _build_gallery_css() -> str:
    return """.ev-gallery-img {
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: cover;
  border-radius: 8px;
}
"""


def _build_before_after_css() -> str:
    return """.ev-ba-slider {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
  gap: 1rem;
  align-items: center;
}
"""


def _build_contact_css() -> str:
    return """.ev-contact-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr));
  gap: 1.25rem;
}
"""


def _build_footer_css() -> str:
    return """.ev-footer {
  background-color: var(--ev-surface);
  border-top: 1px solid var(--ev-border);
  padding: 1.5rem 1.25rem;
  text-align: center;
  color: var(--ev-muted);
}
"""


def _build_section_css_map(
    primary_hex: str, secondary_hex: str, accent_hex: str
) -> dict[str, str]:
    return {
        "base": _build_base_css(primary_hex, secondary_hex, accent_hex),
        "header": _build_header_css(),
        "hero": _build_hero_css(),
        "services": _build_services_css(),
        "gallery": _build_gallery_css(),
        "before-after": _build_before_after_css(),
        "contact": _build_contact_css(),
        "footer": _build_footer_css(),
    }


def _build_css(primary_hex: str, secondary_hex: str, accent_hex: str) -> str:
    css_map = _build_section_css_map(primary_hex, secondary_hex, accent_hex)
    parts: list[str] = []
    for name, css_text in css_map.items():
        parts.append(f"/* section: {name} */\n{css_text.strip()}\n/* endsection: {name} */")
    return "\n\n".join(parts) + "\n"


def _build_js(has_before_after: bool) -> str:
    slider_logic = ""
    if has_before_after:
        slider_logic = """
  var rangeInput = document.querySelector('[data-ev-ba-range]');
  var afterWrap = document.querySelector('[data-ev-ba-after]');
  if (rangeInput && afterWrap) {
    rangeInput.addEventListener('input', function(evt) {
      var target = evt.target;
      if (target && typeof target.value === 'string') {
        afterWrap.setAttribute('data-split', target.value);
      }
    });
  }"""

    return f"""var toggleBtn = document.querySelector('[data-ev-nav-toggle]');
var navDrawer = document.querySelector('[data-ev-nav-drawer]');
if (toggleBtn && navDrawer) {{
  toggleBtn.addEventListener('click', function() {{
    var expanded = toggleBtn.getAttribute('aria-expanded') === 'true';
    var nextState = !expanded;
    toggleBtn.setAttribute('aria-expanded', nextState ? 'true' : 'false');
    navDrawer.setAttribute('data-collapsed', nextState ? 'false' : 'true');
  }});
}}{slider_logic}
"""


def generate_website(project_folder: str | Path) -> GeneratedWebsiteBundle:
    """Synthesize semantic HTML5, responsive CSS, and isolated vanilla JS in website/."""
    project_root = Path(project_folder).resolve()
    project_id = project_root.name

    brand_path = project_root / "design" / "brand.json"
    brief_path = project_root / "design" / "creative-brief.json"
    if not brand_path.is_file() or not brief_path.is_file():
        generate_art_direction(project_root)

    brand_data: dict[str, Any] = {}
    if brand_path.is_file():
        brand_data = json.loads(brand_path.read_text(encoding="utf-8"))

    brief_data: dict[str, Any] = {}
    if brief_path.is_file():
        brief_data = json.loads(brief_path.read_text(encoding="utf-8"))

    facts_path = project_root / "research" / "business-facts.json"
    facts_list: list[dict[str, Any]] = []
    if facts_path.is_file():
        facts_payload = json.loads(facts_path.read_text(encoding="utf-8"))
        facts_list = list(facts_payload.get("facts", []))

    selection_path = project_root / "design" / "image-selection.json"
    selection_data: dict[str, Any] = {}
    if selection_path.is_file():
        selection_data = json.loads(selection_path.read_text(encoding="utf-8"))

    primary_hex = str(brand_data.get("primary_color", FALLBACK_NAVY_HEX))
    secondary_hex = str(brand_data.get("secondary_color", FALLBACK_WARM_AMBER_HEX))
    accent_hex = str(brand_data.get("accent_color", FALLBACK_SOFT_SAGE_HEX))
    business_name = str(
        brief_data.get("business_name") or brand_data.get("business_name") or project_id
    )

    # Extract strictly verified facts
    phone: str | None = None
    address: str | None = None
    hours: str | None = None
    policy: str | None = None
    verified_prices: list[tuple[str, str]] = []
    verified_services: list[str] = []
    has_unverified_pricing = False

    for fact in facts_list:
        category = str(fact.get("category", ""))
        claim_key = str(fact.get("claim_key", ""))
        claim_val = str(fact.get("claim_value", "")).strip()
        is_verified = bool(fact.get("is_verified", False))
        status = str(fact.get("status", "needs_review"))

        if category == "pricing":
            if is_verified and status == "verified":
                label = claim_key.removeprefix("price_").replace("_", " ").title()
                verified_prices.append((label, claim_val))
            else:
                has_unverified_pricing = True
            continue

        if not is_verified or status != "verified":
            continue

        if category == "business_name" and claim_val:
            business_name = claim_val
        elif category == "phone" and phone is None:
            phone = claim_val
        elif category == "address" and address is None:
            address = claim_val
        elif category == "hours" and hours is None:
            hours = claim_val
        elif category == "cancellation_policy" and policy is None:
            policy = claim_val
        elif category == "services" and claim_val not in verified_services:
            verified_services.append(claim_val)

    pricing_needs_review = has_unverified_pricing or not verified_prices

    # Resolve hero and gallery image paths relative to website/index.html
    hero_obj = selection_data.get("hero_image")
    hero_src: str | None = None
    hero_obj_pos = "50% 30%"
    if isinstance(hero_obj, dict) and hero_obj.get("relative_path"):
        cand_file = project_root / str(hero_obj["relative_path"])
        if cand_file.is_file():
            hero_src = f"../{hero_obj['relative_path']}"
            hero_obj_pos = str(hero_obj.get("object_position", "50% 30%"))

    gallery_items: list[tuple[str, str]] = []
    for item in selection_data.get("grooming_gallery", []):
        if isinstance(item, dict) and item.get("relative_path"):
            cand_file = project_root / str(item["relative_path"])
            if cand_file.is_file():
                gallery_items.append(
                    (f"../{item['relative_path']}", str(item.get("object_position", "50% 30%")))
                )

    before_after = _find_before_after_pair(project_root)

    esc_name = html.escape(business_name)
    digits = "".join(c for c in phone if c.isdigit() or c == "+") if phone else ""
    cta_href = f"tel:{digits}" if digits else "#contact"
    cta_text = f"Call {html.escape(phone)}" if phone else "Book Grooming Appointment"

    hero_media_html = ""
    if hero_src:
        hero_media_html = (
            '<div class="ev-hero-media">'
            f'<img class="ev-hero-img" src="{html.escape(hero_src)}" '
            f'alt="{esc_name} Featured Pet" '
            f'style="object-position: {html.escape(hero_obj_pos)};">'
            "</div>"
        )

    # Build Services & Pricing section
    if verified_prices:
        price_cards = "".join(
            f'<div class="ev-card">'
            f'<h3 class="ev-card-title">{html.escape(label)}</h3>'
            f'<span class="ev-price-badge">{html.escape(price)}</span>'
            f"</div>"
            for label, price in verified_prices
        )
        pricing_section_html = f'<div class="ev-grid">{price_cards}</div>'
    else:
        svc_cards = "".join(
            f'<div class="ev-card"><h3 class="ev-card-title">{html.escape(svc)}</h3></div>'
            for svc in verified_services
        )
        pricing_section_html = (
            f"{f'<div class=\"ev-grid\">{svc_cards}</div>' if svc_cards else ''}"
            '<div class="ev-card" style="margin-top: 1rem;">'
            '<h3 class="ev-card-title">Custom Breed &amp; Coat Pricing</h3>'
            "<p>Contact our grooming team directly to receive a verified quote for your pet.</p>"
            f'<p style="margin-top: 0.75rem;"><a class="cta btn" href="{html.escape(cta_href)}">'
            "Inquire for Pricing / Request Custom Quote</a></p>"
            "</div>"
        )

    # Build Gallery section
    gallery_html = ""
    if gallery_items:
        imgs_markup = "".join(
            f'<div class="ev-card">'
            f'<img class="ev-gallery-img" src="{html.escape(src)}" '
            f'alt="{esc_name} Grooming Portfolio {idx}" loading="lazy" '
            f'style="object-position: {html.escape(pos)};">'
            f"</div>"
            for idx, (src, pos) in enumerate(gallery_items, start=1)
        )
        gallery_html = (
            '<section id="gallery" class="ev-section" data-section="gallery">\n'
            '  <h2 class="ev-section-title">Verified Grooming Portfolio</h2>\n'
            f'  <div class="ev-grid">{imgs_markup}</div>\n'
            "</section>"
        )

    # Optional Before/After interactive slider section
    ba_html = ""
    if before_after is not None:
        b_src, a_src = before_after
        ba_html = (
            '<section id="before-after" class="ev-section" data-section="before-after">\n'
            '  <h2 class="ev-section-title">Before &amp; After Transformation</h2>\n'
            '  <div class="ev-ba-slider" data-ev-ba-slider="true">\n'
            '    <div class="ev-card">\n'
            '      <h3 class="ev-card-title">Before Groom</h3>\n'
            f'      <img class="ev-gallery-img" src="{html.escape(b_src)}" alt="Before Grooming">\n'
            '    </div>\n'
            '    <div class="ev-card" data-ev-ba-after="true" data-split="50">\n'
            '      <h3 class="ev-card-title">After Groom</h3>\n'
            f'      <img class="ev-gallery-img" src="{html.escape(a_src)}" alt="After Grooming">\n'
            '    </div>\n'
            '  </div>\n'
            '  <div style="margin-top: 1rem;">\n'
            '    <label for="ev-ba-range">Compare Transformation: </label>\n'
            '    <input id="ev-ba-range" type="range" min="0" max="100" '
            'value="50" data-ev-ba-range="true">\n'
            '  </div>\n'
            "</section>"
        )

    # Contact, Hours & Policy details
    contact_cards: list[str] = []
    if phone:
        contact_cards.append(
            f'<div class="ev-card"><h3 class="ev-card-title">Phone</h3>'
            f"<p>{html.escape(phone)}</p></div>"
        )
    if address:
        contact_cards.append(
            f'<div class="ev-card"><h3 class="ev-card-title">Address</h3>'
            f"<p>{html.escape(address)}</p></div>"
        )
    if hours:
        contact_cards.append(
            f'<div class="ev-card"><h3 class="ev-card-title">Operating Hours</h3>'
            f"<p>{html.escape(hours)}</p></div>"
        )
    if policy:
        contact_cards.append(
            f'<div class="ev-card"><h3 class="ev-card-title">Cancellation Policy</h3>'
            f"<p>{html.escape(policy)}</p></div>"
        )
    if not contact_cards:
        contact_cards.append(
            f'<div class="ev-card"><h3 class="ev-card-title">Contact {esc_name}</h3>'
            "<p>Reach out to schedule your next grooming appointment.</p></div>"
        )

    contact_html = (
        '<section id="contact" class="ev-section" data-section="contact">\n'
        '  <h2 class="ev-section-title">Location, Hours &amp; Policies</h2>\n'
        '  <div class="ev-grid">\n'
        f'    {"".join(contact_cards)}\n'
        '  </div>\n'
        "</section>"
    )

    header_html = (
        '<header class="ev-header" data-section="header">\n'
        '  <nav class="ev-nav" aria-label="Primary Navigation">\n'
        f'    <a class="ev-brand-title" href="#top">{esc_name}</a>\n'
        '    <button class="ev-nav-toggle" type="button" aria-expanded="true"\n'
        '      aria-controls="ev-nav-drawer" data-ev-nav-toggle="true">Menu</button>\n'
        '    <ul id="ev-nav-drawer" class="ev-nav-drawer"\n'
        '      data-ev-nav-drawer="true" data-collapsed="false">\n'
        '      <li><a class="ev-nav-link" href="#services">Services &amp; Pricing</a></li>\n'
        '      <li><a class="ev-nav-link" href="#gallery">Portfolio</a></li>\n'
        '      <li><a class="ev-nav-link" href="#contact">Hours &amp; Contact</a></li>\n'
        '    </ul>\n'
        '  </nav>\n'
        "</header>"
    )

    hero_html = (
        '<section id="hero" class="ev-hero" data-section="hero">\n'
        '  <div>\n'
        f'    <h1 class="ev-hero-title">{esc_name}</h1>\n'
        '    <p class="ev-hero-subtitle">\n'
        '      Authentic, compassionate pet grooming tailored to your companion.\n'
        '    </p>\n'
        f'    <a class="cta btn" href="{html.escape(cta_href)}">{cta_text}</a>\n'
        '  </div>\n'
        f'  {hero_media_html}\n'
        "</section>"
    )

    services_html = (
        '<section id="services" class="ev-section" data-section="services">\n'
        '  <h2 class="ev-section-title">Grooming Services &amp; Pricing</h2>\n'
        f'  {pricing_section_html}\n'
        "</section>"
    )

    footer_html = (
        '<footer class="ev-footer" data-section="footer">\n'
        f'  <p>&copy; {esc_name}. Verified by EditVista Pet Grooming Website Builder Engine.</p>\n'
        "</footer>"
    )

    sections_map: dict[str, str] = {
        "header": header_html,
        "hero": hero_html,
        "services": services_html,
    }
    if gallery_html:
        sections_map["gallery"] = gallery_html
    if ba_html:
        sections_map["before-after"] = ba_html
    sections_map["contact"] = contact_html
    sections_map["footer"] = footer_html

    website_dir = project_root / "website"
    sections_dir = website_dir / "sections"
    css_dir = website_dir / "css"
    js_dir = website_dir / "js"
    sections_dir.mkdir(parents=True, exist_ok=True)
    css_dir.mkdir(parents=True, exist_ok=True)
    js_dir.mkdir(parents=True, exist_ok=True)

    # 1. Output per-section files under website/sections/<name>.html
    section_files: dict[str, Path] = {}
    for name, s_html in sections_map.items():
        s_path = sections_dir / f"{name}.html"
        _atomic_write_text(s_path, s_html.strip() + "\n")
        section_files[name] = s_path

    # 2. Output per-section css under website/css/<name>.css and combined css/styles.css
    section_css_map = _build_section_css_map(primary_hex, secondary_hex, accent_hex)
    section_css_files: dict[str, Path] = {}
    for css_name, css_text in section_css_map.items():
        c_path = css_dir / f"{css_name}.css"
        _atomic_write_text(c_path, css_text.strip() + "\n")
        section_css_files[css_name] = c_path

    combined_css = _build_css(primary_hex, secondary_hex, accent_hex)
    css_path = css_dir / "styles.css"
    _atomic_write_text(css_path, combined_css)

    # 3. Assemble into website/index.html strictly from section files
    html_doc = rebuild_index_from_sections(website_dir, title=business_name)

    js_content = _build_js(has_before_after=before_after is not None)
    index_path = website_dir / "index.html"
    js_path = js_dir / "main.js"

    _atomic_write_text(js_path, js_content)

    # 4. Compute section hashes using ONE unified compute_section_hashes
    section_hashes = compute_section_hashes(html_doc, section_css_map)
    hashes_path = website_dir / "section-hashes.json"
    _atomic_write_text(hashes_path, json.dumps(section_hashes, indent=2))

    return GeneratedWebsiteBundle(
        project_id=project_id,
        index_html_path=index_path,
        css_path=css_path,
        js_path=js_path,
        pricing_needs_review=pricing_needs_review,
        has_before_after_slider=before_after is not None,
        section_hashes_path=hashes_path,
        section_files=section_files,
        section_css_files=section_css_files,
    )


def revise_section(
    name: str,
    new_html: str,
    project_folder: str | Path | None = None,
) -> dict[str, str]:
    """Surgically replace ONLY the named section in sections/<name>.html and rebuild index.html."""
    if project_folder is not None:
        cand = Path(project_folder).resolve()
        website_dir = cand / "website" if (cand / "website").is_dir() else cand
    else:
        website_dir = Path("./website").resolve()

    if not website_dir.is_dir():
        raise ValueError(f"Website directory not found at {website_dir}")

    sections_dir = website_dir / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)

    # 1. Validate new_html (no script/inline handlers/external URLs, data-section present, size cap)
    validate_section_html(name, new_html)

    cleaned_new = new_html.strip()

    # 2. Update website/sections/<name>.html
    target_sec_file = sections_dir / f"{name}.html"
    _atomic_write_text(target_sec_file, cleaned_new + "\n")

    # 3. Always rebuild website/index.html from section files
    rebuilt_doc = rebuild_index_from_sections(website_dir)

    # 4. Recompute and write website/section-hashes.json using ONE compute_section_hashes
    section_hashes = compute_section_hashes(rebuilt_doc, project_folder=website_dir)

    hashes_path = website_dir / "section-hashes.json"
    _atomic_write_text(hashes_path, json.dumps(section_hashes, indent=2))
    return section_hashes
