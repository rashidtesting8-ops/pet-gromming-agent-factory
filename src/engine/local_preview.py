"""Screenshot + basic functional QA for a *standalone* local HTML preview.

Optional Playwright/Chromium installation. Does not replace a human aesthetic review.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from engine.contracts import atomic_write_json

WIDTHS: tuple[int, ...] = (1440, 1024, 768, 390, 360)


def check_local_html(
    html: str | Path,
    output: str | Path | None = None,
    *,
    widths: Sequence[int] = WIDTHS,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "Install requirements-browser.txt and run: python -m playwright install chromium"
        ) from exc
    html_path = Path(html).resolve()
    if not html_path.is_file() or html_path.suffix.lower() not in (".html", ".htm"):
        raise ValueError("A real local .html file is required")
    out = Path(output).resolve() if output else html_path.parent / "qa-screenshots"
    out.mkdir(parents=True, exist_ok=True)
    outcomes: list[dict[str, Any]] = []
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
                page.wait_for_timeout(500)
                result = page.evaluate(
                    """() => {
                    const doc=document.documentElement;
                    const images=[...document.images];
                    const badImages=images
                        .filter(i=>!i.complete || i.naturalWidth===0)
                        .map(i=>i.getAttribute('src')||'empty');
                    const links=[...document.querySelectorAll('a[href]')];
                    const badLinks=links.filter(a=>{
                        const h=a.getAttribute('href');
                        return !h || h==='#' || h.toLowerCase().startsWith('javascript:');
                    }).map(a=>a.textContent.trim().slice(0,60));
                    const outside=[...document.querySelectorAll('body *')].filter(e=>{
                         const r=e.getBoundingClientRect(),s=getComputedStyle(e);
                         return (
                             r.width>0 && s.position!=='fixed' && r.right>innerWidth+2 && r.left>=0
                         );
                    }).slice(0,12).map(e=>(e.tagName+'.'+e.className).slice(0,120));
                    return {
                        scrollWidth:doc.scrollWidth,
                        overflow:doc.scrollWidth>innerWidth+2,
                        badImages,
                        badLinks,
                        outside
                    };
                }"""
                )
                shot = out / f"{width}.png"
                page.screenshot(path=str(shot), full_page=True, animations="disabled")
                outcomes.append(
                    {"width": width, "screenshot": str(shot), "runtime_errors": errors, **result}
                )
                page.close()
        finally:
            browser.close()
    report: dict[str, Any] = {
        "html": str(html_path),
        "checks": outcomes,
        "technical_pass": all(
            not r["overflow"] and not r["badImages"] and not r["runtime_errors"] for r in outcomes
        ),
        "human_visual_approval_required": True,
    }
    atomic_write_json(out / "report.json", report, ensure_ascii=True)
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--output")
    args = ap.parse_args()
    print(json.dumps(check_local_html(args.html, args.output), indent=2))


if __name__ == "__main__":
    main()
