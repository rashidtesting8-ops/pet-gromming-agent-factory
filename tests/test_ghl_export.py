"""Tests for the GoHighLevel custom code exporter in app/ghl_exporter.py."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.ghl_exporter import (
    GlobalLeakageError,
    export_ghl_snippet,
    find_unscoped_selectors,
    scope_css,
)


def test_css_scoping_prefixes_all_selectors_and_moves_root_vars() -> None:
    raw_css = """
    :root {
      --brand-primary: #1e3a8a;
      --brand-accent: #f59e0b;
    }
    html, body {
      margin: 0;
      font-family: sans-serif;
    }
    h1, h2, p {
      color: var(--brand-primary);
    }
    .hero-title {
      font-size: 2.5rem;
    }
    @media (max-width: 768px) {
      .hero-title, p {
        font-size: 1.75rem;
      }
    }
    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }
    """
    root_sel = "#ghl-ev-engine-root-paws-salon"
    scoped = scope_css(raw_css, root_sel)

    assert ":root" not in scoped
    assert f"{root_sel} {{" in scoped
    assert f"{root_sel} h1, {root_sel} h2, {root_sel} p {{" in scoped
    assert f"{root_sel} .hero-title {{" in scoped
    assert f"{root_sel} .hero-title, {root_sel} p {{" in scoped
    assert "@keyframes fadeIn" in scoped
    assert find_unscoped_selectors(scoped, root_sel) == []


def test_export_ghl_snippet_sanitizes_markup_scopes_css_and_isolates_js(
    tmp_path: Path,
) -> None:
    project = tmp_path / "paws-salon"
    (project / "delivery").mkdir(parents=True)

    (project / "delivery" / "approved-homepage.html").write_text(
        """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Paws Salon</title>
  <style>
    :root { --brand: #1e3a8a; }
    .hero-title { color: var(--brand); }
    p { line-height: 1.6; }
    body { background: #fff; }
    h1 { color: #111; }
  </style>
</head>
<body>
  <header><h1 class="hero-title">Paws Salon</h1></header>
  <main><p>Gentle pet grooming.</p></main>
  <script>
const toggle = root.querySelector('.hero-title');
if (toggle) {
  toggle.setAttribute('data-ready', 'true');
}
  </script>
</body>
</html>
""",
        encoding="utf-8",
    )

    output_html = export_ghl_snippet(project)

    out_file = project / "delivery" / "ghl-ready.html"
    assert out_file.is_file()
    assert out_file.read_text(encoding="utf-8") == output_html

    # 1. Markup sanitization assertions
    lower_out = output_html.lower()
    assert "<!doctype" not in lower_out
    assert "<html" not in lower_out
    assert "<head>" not in lower_out and "</head>" not in lower_out
    assert "<body" not in lower_out
    assert '<div id="ghl-ev-engine-root-paws-salon">' in output_html

    # 2. CSS scoping assertions: zero unscoped selectors in the final output
    style_start = output_html.index("<style>") + len("<style>")
    style_end = output_html.index("</style>")
    extracted_css = output_html[style_start:style_end]
    assert find_unscoped_selectors(extracted_css, "#ghl-ev-engine-root-paws-salon") == []
    assert ":root" not in extracted_css
    assert "#ghl-ev-engine-root-paws-salon .hero-title" in extracted_css
    assert "#ghl-ev-engine-root-paws-salon p" in extracted_css
    assert "#ghl-ev-engine-root-paws-salon h1" in extracted_css

    # 3. JavaScript isolation & MutationObserver assertions
    assert "(function(){ 'use strict';" in output_html
    assert "})();" in output_html
    assert "MutationObserver" in output_html


def test_export_ghl_blocks_global_window_or_document_leakage(tmp_path: Path) -> None:
    project = tmp_path / "leaky-salon"
    (project / "delivery").mkdir(parents=True)
    (project / "delivery" / "approved-homepage.html").write_text(
        "<html><body><h1>Salon</h1>"
        "<script>window.myGlobalState = { hacked: true };</script></body></html>",
        encoding="utf-8",
    )

    with pytest.raises(GlobalLeakageError):
        export_ghl_snippet(project)


def test_export_ghl_refuses_when_only_website_exists_without_delivery(tmp_path: Path) -> None:
    """Exporter must only read from delivery/, refusing if only website/index.html exists."""
    project = tmp_path / "unapproved-salon"
    (project / "website").mkdir(parents=True)
    (project / "website" / "index.html").write_text(
        "<html><body><h1>Unapproved</h1></body></html>",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="delivery"):
        export_ghl_snippet(project)


def test_scope_css_preserves_semicolons_inside_quoted_data_uris() -> None:
    """scope_css must not split CSS declarations on semicolons inside quoted url('data:...')."""
    from app.ghl_exporter import scope_css

    raw_css = (
        '.hero-icon { background-image: url("data:image/svg+xml;utf8,<svg></svg>"); '
        "color: #1B365D; }"
    )
    scoped = scope_css(raw_css, "#ev-ghl-root")
    assert 'url("data:image/svg+xml;utf8,<svg></svg>")' in scoped
    assert "data:image/svg+xml; utf8," not in scoped


