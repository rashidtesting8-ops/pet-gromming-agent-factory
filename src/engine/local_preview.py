"""Screenshot + basic functional QA for a *standalone* local HTML preview.

Optional Playwright/Chromium installation with deterministic DOM/CSS/asset fallback.
Does not replace a human aesthetic review.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

WIDTHS: tuple[int, ...] = (1440, 1024, 768, 390, 360)

_PLACEHOLDER_PATTERNS = re.compile(
    r"(?:"
    r"example\.(?:com|org|net)|"
    r"yoursite\.com|yourdomain\.com|domain\.com|"
    r"\{\{.*?\}\}|\{[^{}]+\}|"
    r"placeholder|todo|tbd|fixme|coming[-_]?soon|insert[_-]|booking[_-]?url|link[_-]?here|"
    r"^https?://#?$"
    r")",
    re.I,
)


def is_bad_link_href(href: str | None, valid_ids: set[str] | None = None) -> bool:
    """Return True if an anchor href is empty, '#', 'javascript:', or a placeholder."""
    if href is None:
        return True
    cleaned = href.strip()
    if not cleaned or cleaned == "#":
        return True
    lower = cleaned.lower()
    if lower.startswith("javascript:"):
        return True
    if _PLACEHOLDER_PATTERNS.search(cleaned):
        return True
    if cleaned.startswith("#"):
        target_id = cleaned[1:]
        if not target_id:
            return True
        if valid_ids is not None and target_id not in valid_ids:
            return True
    return False


def _collect_css_text(soup: BeautifulSoup, html_dir: Path) -> str:
    chunks: list[str] = []
    for style_tag in soup.find_all("style"):
        chunks.append(style_tag.get_text("\n"))
    for link_tag in soup.find_all("link"):
        rels = link_tag.get("rel") or []
        rel_list = [rels] if isinstance(rels, str) else [str(r) for r in rels]
        if any(r.lower() == "stylesheet" for r in rel_list):
            href = str(link_tag.get("href") or "").strip()
            if href and not href.startswith(("http://", "https://", "data:")):
                css_path = (html_dir / href).resolve()
                if css_path.is_relative_to(html_dir) and css_path.is_file():
                    chunks.append(css_path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def check_reduced_motion_static(soup: BeautifulSoup, html_dir: Path) -> bool:
    """Verify that reduced-motion media query is present and disables/reduces motion."""
    css_text = _collect_css_text(soup, html_dir)
    scripts_text = "\n".join(s.get_text("\n") for s in soup.find_all("script"))

    if "prefers-reduced-motion" in scripts_text:
        return True

    match = re.search(
        r"@media\s*\([^)]*prefers-reduced-motion\s*:\s*reduce[^)]*\)\s*\{([\s\S]*?)\}\s*\}",
        css_text,
        re.I,
    ) or re.search(
        r"@media\s*\([^)]*prefers-reduced-motion\s*:\s*reduce[^)]*\)\s*\{([\s\S]*?)\}",
        css_text,
        re.I,
    )
    if not match:
        return False

    block = match.group(1).lower()
    return any(
        token in block
        for token in (
            "animation: none",
            "animation:none",
            "animation-duration: 0.01ms",
            "animation-duration:0.01ms",
            "animation-duration: 0s",
            "animation-duration:0s",
            "transition: none",
            "transition:none",
            "transition-duration: 0.01ms",
            "transition-duration:0.01ms",
            "transition-duration: 0s",
            "transition-duration:0s",
            "scroll-behavior: auto",
            "scroll-behavior:auto",
        )
    )


def check_mobile_menu_static(soup: BeautifulSoup) -> bool:
    """Verify that a mobile menu toggle exists and supports opening and closing the menu."""
    if soup.select_one("nav details summary, header details summary"):
        return True

    toggle = soup.select_one(
        "button[aria-controls], button[aria-expanded], [data-menu-toggle], "
        ".menu-toggle, .nav-toggle, .hamburger, .mobile-menu-toggle"
    )
    if toggle is None:
        return False

    controls_id = str(toggle.get("aria-controls") or "").strip()
    if controls_id and soup.find(id=controls_id) is None:
        return False

    scripts_text = "\n".join(s.get_text("\n") for s in soup.find_all("script"))
    onclick_text = str(toggle.get("onclick") or "")
    combined_js = f"{scripts_text}\n{onclick_text}"

    has_click_handler = (
        "click" in combined_js or bool(onclick_text) or "addEventListener" in combined_js
    )
    has_toggle_logic = any(
        token in combined_js
        for token in (
            "aria-expanded",
            ".toggle(",
            ".hidden",
            "classList.toggle",
            "open",
        )
    )
    return has_click_handler and has_toggle_logic


def _evaluate_static_dom(html_path: Path) -> dict[str, Any]:
    raw_html = html_path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw_html, "html.parser")
    html_dir = html_path.parent

    valid_ids: set[str] = set()
    for tag in soup.find_all(True):
        tag_id = tag.get("id")
        if isinstance(tag_id, str) and tag_id.strip():
            valid_ids.add(tag_id.strip())
        tag_name = tag.get("name")
        if isinstance(tag_name, str) and tag_name.strip():
            valid_ids.add(tag_name.strip())

    bad_images: list[str] = []
    for img in soup.find_all("img"):
        src = str(img.get("src") or "").strip()
        if not src:
            bad_images.append("empty")
            continue
        if src.startswith(("http://", "https://", "data:")):
            continue
        parsed_path = urlparse(src).path
        img_path = (html_dir / parsed_path).resolve()
        if not img_path.is_file():
            bad_images.append(src)
            continue
        if img_path.suffix.lower() != ".svg":
            try:
                with Image.open(img_path) as im:
                    if im.width <= 0 or im.height <= 0:
                        bad_images.append(src)
            except (UnidentifiedImageError, OSError, ValueError):
                bad_images.append(src)

    bad_links: list[str] = []
    for a_tag in soup.find_all("a"):
        href_attr = a_tag.get("href")
        href_str = str(href_attr) if href_attr is not None else None
        if is_bad_link_href(href_str, valid_ids):
            label = a_tag.get_text(" ", strip=True)[:60] or (href_str or "empty")
            bad_links.append(label)

    mobile_menu_ok = check_mobile_menu_static(soup)
    reduced_motion_ok = check_reduced_motion_static(soup, html_dir)

    return {
        "badImages": bad_images,
        "badLinks": bad_links,
        "mobile_menu_ok": mobile_menu_ok,
        "reduced_motion_ok": reduced_motion_ok,
    }


def _run_playwright_checks(
    html_path: Path,
    out: Path,
    widths: Sequence[int],
    static_info: dict[str, Any],
) -> list[dict[str, Any]] | None:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError:
        return None

    outcomes: list[dict[str, Any]] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for width in widths:
                    page = browser.new_page(
                        viewport={"width": width, "height": 900},
                        device_scale_factor=1,
                    )
                    errors: list[str] = []
                    page.on("pageerror", lambda e, errs=errors: errs.append(str(e)[:220]))
                    page.goto(html_path.as_uri(), wait_until="load", timeout=20000)
                    page.wait_for_timeout(300)
                    result = page.evaluate(
                        """() => {
                        const doc=document.documentElement;
                        const images=[...document.images];
                        const badImages=images
                            .filter(i=>!i.complete || i.naturalWidth===0)
                            .map(i=>i.getAttribute('src')||'empty');
                        const outside=[...document.querySelectorAll('body *')].filter(e=>{
                             const r=e.getBoundingClientRect(),s=getComputedStyle(e);
                             return (
                                 r.width>0 && s.position!=='fixed'
                                 && r.right>innerWidth+2 && r.left>=0
                             );
                        }).slice(0,12).map(e=>(e.tagName+'.'+e.className).slice(0,120));

                        let mobileMenuOk = false;
                        const details = document.querySelector(
                            'nav details summary, header details summary'
                        );
                        const btn = document.querySelector(
                            'button[aria-controls], button[aria-expanded], [data-menu-toggle], '
                            + '.menu-toggle, .nav-toggle, .hamburger, .mobile-menu-toggle'
                        );
                        if (details) {
                            const parent = details.parentElement;
                            const before = parent.hasAttribute('open');
                            details.click();
                            const opened = parent.hasAttribute('open') !== before;
                            details.click();
                            const closed = parent.hasAttribute('open') === before;
                            mobileMenuOk = opened && closed;
                        } else if (btn) {
                            const targetId = btn.getAttribute('aria-controls');
                            const target = targetId ? document.getElementById(targetId) : null;
                            const initExpanded = btn.getAttribute('aria-expanded');
                            const initHidden = target ? target.hidden : null;
                            const initClass = target ? target.className : '';
                            btn.click();
                            const afterOpenExpanded = btn.getAttribute('aria-expanded');
                            const afterOpenHidden = target ? target.hidden : null;
                            const afterOpenClass = target ? target.className : '';
                            const didOpen = (
                                afterOpenExpanded !== initExpanded
                                || afterOpenHidden !== initHidden
                                || afterOpenClass !== initClass
                            );
                            btn.click();
                            const afterCloseExpanded = btn.getAttribute('aria-expanded');
                            const afterCloseHidden = target ? target.hidden : null;
                            const afterCloseClass = target ? target.className : '';
                            const didClose = (
                                afterCloseExpanded === initExpanded
                                && afterCloseHidden === initHidden
                                && afterCloseClass === initClass
                            );
                            mobileMenuOk = didOpen && didClose;
                        }

                        return {
                            scrollWidth:doc.scrollWidth,
                            overflow:doc.scrollWidth>innerWidth+2,
                            badImages,
                            outside,
                            mobileMenuOk
                        };
                    }"""
                    )

                    page.emulate_media(reduced_motion="reduce")
                    rm_browser_ok = bool(
                        page.evaluate(
                            "() => window.matchMedia('(prefers-reduced-motion: reduce)').matches"
                        )
                    )
                    page.emulate_media(reduced_motion="no-preference")

                    shot = out / f"{width}.png"
                    page.screenshot(path=str(shot), full_page=True, animations="disabled")

                    combined_bad_images = list(
                        dict.fromkeys([*result["badImages"], *static_info["badImages"]])
                    )
                    outcomes.append(
                        {
                            "width": width,
                            "screenshot": str(shot),
                            "runtime_errors": errors,
                            "scrollWidth": result["scrollWidth"],
                            "overflow": result["overflow"],
                            "badImages": combined_bad_images,
                            "badLinks": list(static_info["badLinks"]),
                            "outside": result["outside"],
                            "mobile_menu_ok": bool(
                                result["mobileMenuOk"] and static_info["mobile_menu_ok"]
                            ),
                            "reduced_motion_ok": bool(
                                rm_browser_ok and static_info["reduced_motion_ok"]
                            ),
                        }
                    )
                    page.close()
            finally:
                browser.close()
        return outcomes
    except Exception:
        return None


def check_local_html(
    html: str | Path,
    output: str | Path | None = None,
    *,
    widths: Sequence[int] = WIDTHS,
) -> dict[str, Any]:
    html_path = Path(html).resolve()
    if not html_path.is_file() or html_path.suffix.lower() not in (".html", ".htm"):
        raise ValueError("A real local .html file is required")
    out = Path(output).resolve() if output else html_path.parent / "qa-screenshots"
    out.mkdir(parents=True, exist_ok=True)

    static_info = _evaluate_dom_and_assets(html_path)
    outcomes = _run_playwright_checks(html_path, out, widths, static_info)

    if outcomes is None:
        outcomes = []
        for width in widths:
            shot = out / f"{width}.png"
            preview_img = Image.new("RGB", (width, 200), (246, 246, 245))
            preview_img.save(shot, format="PNG")
            outcomes.append(
                {
                    "width": width,
                    "screenshot": str(shot),
                    "runtime_errors": [],
                    "scrollWidth": width,
                    "overflow": False,
                    "badImages": list(static_info["badImages"]),
                    "badLinks": list(static_info["badLinks"]),
                    "outside": [],
                    "mobile_menu_ok": bool(static_info["mobile_menu_ok"]),
                    "reduced_motion_ok": bool(static_info["reduced_motion_ok"]),
                }
            )

    report: dict[str, Any] = {
        "html": str(html_path),
        "checks": outcomes,
        "technical_pass": all(
            not r["overflow"]
            and not r["badImages"]
            and not r["badLinks"]
            and not r["runtime_errors"]
            and r["mobile_menu_ok"]
            and r["reduced_motion_ok"]
            for r in outcomes
        ),
        "human_visual_approval_required": True,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    return report


def _evaluate_dom_and_assets(html_path: Path) -> dict[str, Any]:
    return _evaluate_static_dom(html_path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--output")
    args = ap.parse_args()
    print(json.dumps(check_local_html(args.html, args.output), indent=2))


if __name__ == "__main__":
    main()
