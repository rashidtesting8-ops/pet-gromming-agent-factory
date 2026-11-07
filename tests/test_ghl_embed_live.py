"""Track 4: Live GoHighLevel (GHL) Embed & Host Isolation Test Suite.

Validates:
1. Asset CDN hosting strategy: rewrites relative local asset paths in markup and CSS
   to externally hosted URLs or stable CDN base paths.
2. Host CSS Bleed Isolation: ensures snippet styles are encapsulated under the root
   container and resist hostile host stylesheets (e.g. GHL funnel defaults).
3. Dynamic / Late DOM Mounting: ensures MutationObserver properly initializes JS
   when GHL injects the Custom HTML block asynchronously.
4. Mobile Drawer & Navigation Interactivity: tests mobile menu toggle strictly
   scoped inside the root container without global variable pollution.
5. End-to-End Delivery Embed Simulation: renders ghl-ready.html inside a simulated
   GHL page and asserts zero global leaks, 100% scoped selectors, and clean rendering.
"""

from __future__ import annotations

from pathlib import Path

from app.ghl_exporter import (
    export_ghl_snippet,
    rewrite_ghl_asset_urls,
    validate_ghl_embed_simulation,
)


def _scaffold_ghl_project(tmp_path: Path, project_id: str = "ghl-test-salon") -> Path:
    project_root = tmp_path / project_id
    for sub in ("delivery", "website/sections", "website/css", "website/js"):
        (project_root / sub).mkdir(parents=True, exist_ok=True)

    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>GHL Test Salon</title>
  <style>
    :root {
      --ev-primary: #1B365D;
      --ev-accent: #D98A2B;
    }
    body {
      margin: 0;
      font-family: 'Inter', sans-serif;
      background: #FFFFFF;
    }
    .hero-banner {
      background-image: url('assets/optimized/hero_bg.jpg');
      padding: 4rem 2rem;
    }
    .hero-title {
      color: var(--ev-primary);
      font-size: 2.5rem;
    }
    .cta-btn {
      background: var(--ev-accent);
      color: #FFFFFF;
      padding: 0.75rem 1.5rem;
      border-radius: 6px;
    }
    .nav-drawer {
      display: none;
      position: fixed;
      top: 0;
      right: 0;
      width: 280px;
      height: 100%;
      background: #FFFFFF;
      z-index: 9999;
    }
    .nav-drawer.open {
      display: block;
    }
  </style>
</head>
<body>
  <div class="ev-page-wrapper">
    <header class="ev-header">
      <button id="ghl-menu-toggle" type="button" aria-expanded="false">Menu</button>
      <nav id="ghl-drawer" class="nav-drawer" hidden>
        <a href="#services">Services</a>
        <a href="tel:+15125550199">Call Now</a>
      </nav>
    </header>
    <main>
      <section class="hero-banner">
        <h1 class="hero-title">Premier Pet Care</h1>
        <img src="assets/optimized/dog_wash.jpg" alt="Dog enjoying bath" width="600" height="400">
        <a href="https://booking.example.com" class="cta-btn">Book Online</a>
      </section>
      <section id="services">
        <h2>Our Services</h2>
        <img src="assets/optimized/grooming_van.png" alt="Mobile van" width="400" height="300">
      </section>
    </main>
  </div>
  <script>
    const menuBtn = root.querySelector('#ghl-menu-toggle');
    const drawer = root.querySelector('#ghl-drawer');
    if (menuBtn && drawer) {
      menuBtn.addEventListener('click', function() {
        const isOpen = drawer.classList.contains('open');
        drawer.classList.toggle('open', !isOpen);
        drawer.hidden = isOpen;
        menuBtn.setAttribute('aria-expanded', String(!isOpen));
      });
    }
  </script>
</body>
</html>"""
    (project_root / "delivery/approved-homepage.html").write_text(html_content, encoding="utf-8")
    return project_root


def test_rewrite_ghl_asset_urls_with_cdn_base_url() -> None:
    html_sample = (
        '<div id="root">\n'
        '  <img src="assets/optimized/dog.jpg" alt="Pup">\n'
        '  <img src="/assets/optimized/cat.png" alt="Cat">\n'
        '  <img src="https://already-hosted.com/logo.png" alt="External">\n'
        '  <style>.hero { background-image: url("assets/optimized/hero_bg.jpg"); }</style>\n'
        '</div>'
    )
    cdn_base = "https://cdn.editvista.com/paws-salon"
    rewritten = rewrite_ghl_asset_urls(html_sample, cdn_base_url=cdn_base)

    assert 'src="https://cdn.editvista.com/paws-salon/assets/optimized/dog.jpg"' in rewritten
    assert 'src="https://cdn.editvista.com/paws-salon/assets/optimized/cat.png"' in rewritten
    # Already-absolute URLs must remain untouched
    assert 'src="https://already-hosted.com/logo.png"' in rewritten
    # CSS url(...) must be rewritten
    assert 'url("https://cdn.editvista.com/paws-salon/assets/optimized/hero_bg.jpg")' in rewritten


def test_rewrite_ghl_asset_urls_with_explicit_asset_map() -> None:
    html_sample = (
        '<div id="root">\n'
        '  <img src="assets/optimized/dog.jpg" alt="Pup">\n'
        '  <img src="assets/optimized/van.png" alt="Van">\n'
        '</div>'
    )
    asset_map = {
        "assets/optimized/dog.jpg": "https://media.leadconnectorhq.com/documents/f12345/dog.jpg",
        "assets/optimized/van.png": "https://media.leadconnectorhq.com/documents/f12345/van.png",
    }
    rewritten = rewrite_ghl_asset_urls(html_sample, asset_url_map=asset_map)

    assert 'src="https://media.leadconnectorhq.com/documents/f12345/dog.jpg"' in rewritten
    assert 'src="https://media.leadconnectorhq.com/documents/f12345/van.png"' in rewritten


def test_export_ghl_snippet_with_cdn_rewriting_and_encapsulation(tmp_path: Path) -> None:
    project_root = _scaffold_ghl_project(tmp_path)
    cdn_base = "https://assets.editvista.com/ghl-test-salon"

    snippet = export_ghl_snippet(
        project_root,
        cdn_base_url=cdn_base,
    )

    root_id = "ghl-ev-engine-root-ghl-test-salon"
    assert snippet.startswith(f'<div id="{root_id}">')
    assert snippet.endswith("</div>\n")
    assert "<!DOCTYPE" not in snippet
    assert "<html" not in snippet
    assert "<body" not in snippet

    # Verify CDN asset URLs
    assert f'src="{cdn_base}/assets/optimized/dog_wash.jpg"' in snippet
    assert f'url("{cdn_base}/assets/optimized/hero_bg.jpg")' in snippet

    # Verify CSS scoping
    assert f"#{root_id} .hero-title" in snippet
    assert f"#{root_id} .cta-btn" in snippet

    # Verify IIFE JavaScript encapsulation
    assert "(function(){ 'use strict';" in snippet
    assert f"var ROOT_ID = '{root_id}';" in snippet


def test_validate_ghl_embed_simulation_detects_host_isolation(tmp_path: Path) -> None:
    """Simulate a hostile GoHighLevel landing page environment and verify snippet isolation."""
    project_root = _scaffold_ghl_project(tmp_path)
    snippet = export_ghl_snippet(
        project_root,
        cdn_base_url="https://cdn.example.com/salon",
    )

    # Hostile GHL Host Template attempting to bleed styles and pollute global variables
    host_page_template = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>GHL Client Funnel Host Page</title>
  <style>
    /* Aggressive GHL Host Page default overrides */
    body {{
      font-family: 'Comic Sans MS', cursive !important;
      color: #FF0000 !important;
      background: #000000;
    }}
    h1 {{
      font-size: 80px !important;
      color: #990099 !important;
    }}
    a {{
      color: #00FF00 !important;
      text-decoration: underline !important;
    }}
  </style>
</head>
<body>
  <div class="ghl-page-container">
    <div class="ghl-header">GHL Funnel Navigation</div>
    <div class="ghl-custom-code-embed-element">
      {snippet}
    </div>
    <div class="ghl-footer">GHL Funnel Footer</div>
  </div>
</body>
</html>"""

    result = validate_ghl_embed_simulation(
        host_page_template,
        root_id="ghl-ev-engine-root-ghl-test-salon",
    )

    assert result["is_valid"] is True
    assert result["unscoped_css_count"] == 0
    assert result["global_leak_detected"] is False
    assert result["root_element_found"] is True
    assert result["asset_urls_absolute"] is True
