from __future__ import annotations

import tempfile
from pathlib import Path

from app.local_preview import check_local_html
from PIL import Image

PASSING_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Pup Palace Grooming</title>
  <style>
    body { margin: 0; font-family: sans-serif; }
    .hero-cta { transition: transform 0.2s ease; }
    .nav-menu[hidden] { display: none; }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
        scroll-behavior: auto !important;
      }
    }
  </style>
</head>
<body>
  <header>
    <nav aria-label="Main Navigation">
      <button
        id="menu-btn"
        class="menu-toggle"
        aria-expanded="false"
        aria-controls="nav-menu"
        type="button"
      >Menu</button>
      <div id="nav-menu" class="nav-menu" hidden>
        <a href="#services">Services</a>
        <a href="tel:+442079460192">Call Us</a>
        <a class="cta" href="https://booking.puppalacesalon.com/book">Book Now</a>
      </div>
    </nav>
  </header>
  <main>
    <section id="hero">
      <img src="dog.png" alt="Happy groomed poodle" width="320" height="240">
      <a class="hero-cta" href="https://booking.puppalacesalon.com/book">Book Appointment</a>
    </section>
    <section id="services">
      <h2>Our Grooming Services</h2>
    </section>
  </main>
  <script>
    const btn = document.getElementById('menu-btn');
    const menu = document.getElementById('nav-menu');
    if (btn && menu) {
      btn.addEventListener('click', () => {
        const expanded = btn.getAttribute('aria-expanded') === 'true';
        btn.setAttribute('aria-expanded', String(!expanded));
        menu.hidden = expanded;
        menu.classList.toggle('open', !expanded);
      });
    }
  </script>
</body>
</html>
"""

PLACEHOLDER_LINKS_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Draft Grooming Page</title>
  <style>
    @media (prefers-reduced-motion: reduce) {
      * { animation: none !important; transition: none !important; }
    }
  </style>
</head>
<body>
  <header>
    <nav>
      <button
        id="menu-btn"
        class="menu-toggle"
        aria-expanded="false"
        aria-controls="nav-menu"
        type="button"
      >Menu</button>
      <div id="nav-menu" hidden>
        <a href="#">Services</a>
        <a href="">Prices</a>
        <a href="javascript:void(0)">Reviews</a>
        <a href="https://example.com/booking">Book Placeholder</a>
        <a href="{{BOOKING_URL}}">Book Token</a>
      </div>
    </nav>
  </header>
  <main>
    <img src="dog.png" alt="Dog" width="320" height="240">
  </main>
  <script>
    const btn = document.getElementById('menu-btn');
    const menu = document.getElementById('nav-menu');
    if (btn && menu) {
      btn.addEventListener('click', () => {
        const expanded = btn.getAttribute('aria-expanded') === 'true';
        btn.setAttribute('aria-expanded', String(!expanded));
        menu.hidden = expanded;
      });
    }
  </script>
</body>
</html>
"""


def _write_test_image(folder: Path) -> None:
    im = Image.new("RGB", (320, 240), (200, 120, 100))
    im.save(folder / "dog.png", format="PNG")


def test_local_preview_passing_html_fixture() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_test_image(root)
        html_file = root / "index.html"
        html_file.write_text(PASSING_HTML, encoding="utf-8")

        report = check_local_html(html_file, root / "qa-out")
        assert report["technical_pass"] is True
        assert len(report["checks"]) == 5
        for chk in report["checks"]:
            assert chk["badLinks"] == []
            assert chk["badImages"] == []
            assert chk["mobile_menu_ok"] is True
            assert chk["reduced_motion_ok"] is True


def test_local_preview_fails_on_placeholder_and_bad_links() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_test_image(root)
        html_file = root / "bad.html"
        html_file.write_text(PLACEHOLDER_LINKS_HTML, encoding="utf-8")

        report = check_local_html(html_file, root / "qa-out")
        assert report["technical_pass"] is False
        first = report["checks"][0]
        assert len(first["badLinks"]) == 5
        assert "Services" in first["badLinks"]
        assert "Prices" in first["badLinks"]
        assert "Reviews" in first["badLinks"]
        assert "Book Placeholder" in first["badLinks"]
        assert "Book Token" in first["badLinks"]


def test_local_preview_fails_when_mobile_menu_or_reduced_motion_missing() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_test_image(root)
        html_file = root / "no_a11y.html"
        html_file.write_text(
            """<!doctype html>
<html>
<head>
  <style>.cta { animation: pulse 1s infinite; }</style>
</head>
<body>
  <nav><a href="https://booking.puppalacesalon.com/book">Book</a></nav>
  <img src="dog.png" alt="Dog">
</body>
</html>""",
            encoding="utf-8",
        )
        report = check_local_html(html_file, root / "qa-out")
        assert report["technical_pass"] is False
        first = report["checks"][0]
        assert first["mobile_menu_ok"] is False
        assert first["reduced_motion_ok"] is False
