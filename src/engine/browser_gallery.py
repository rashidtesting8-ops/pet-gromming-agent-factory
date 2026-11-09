"""Optional JS-rendered gallery capture for discoverable pages; browser is ephemeral.

Use on explicitly selected public site URLs only. Does not log into social media,
bypass restrictions, or promise capture of every media item.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from engine.collector import (
    _default_resolver,
    build_collector_session,
    collect_page_text,
    download_one,
    grab_media,
    safe_url,
    validate_ip_address,
)


def verify_browser_url(url: str, *, resolver: Any = None) -> list[str]:
    """Validate URL syntax and verify all DNS records resolve exclusively to public IPs."""
    safe_url(url)
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().strip("[]")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    active_resolver = resolver or _default_resolver
    records = list(active_resolver(host, port))
    if not records:
        raise ValueError(f"DNS resolution returned no addresses for {host!r}")
    verified_ips: list[str] = []
    for entry in records:
        sockaddr = entry[4]
        raw_ip = str(sockaddr[0])
        verified_ips.append(validate_ip_address(raw_ip))
    return verified_ips


def render_gallery(
    url: str,
    project: str | Path,
    *,
    max_scrolls: int = 5,
    download: bool = True,
    max_files: int = 50,
    resolver: Any = None,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Install requirements-browser.txt and Chromium") from exc
    verify_browser_url(url, resolver=resolver)
    project_path = Path(project).resolve()
    pages_file = project_path / "research/pages.json"
    if not pages_file.is_file():
        raise ValueError("Collect the site first to create research/pages.json")
    pages = json.loads(pages_file.read_text(encoding="utf8"))
    original_host = urlparse(pages[0]["url"]).hostname
    if (urlparse(url).hostname or "").removeprefix("www.") != (original_host or "").removeprefix(
        "www."
    ):
        raise ValueError("Gallery URL must belong to the already researched website")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})

            def _enforce_ssrf_boundary(route: Any) -> None:
                try:
                    verify_browser_url(route.request.url, resolver=resolver)
                    route.continue_()
                except Exception:
                    route.abort()

            page.route("**/*", _enforce_ssrf_boundary)
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            for _ in range(max(0, min(6, max_scrolls))):
                page.evaluate("window.scrollTo(0,document.body.scrollHeight)")
                page.wait_for_timeout(350)
            rendered = page.content()
            if len(rendered.encode("utf8")) > 5_000_000:
                raise ValueError("Rendered page too large")
        finally:
            browser.close()
    soup = BeautifulSoup(rendered, "html.parser")
    media = grab_media(soup, url)
    out: dict[str, Any] = {
        "url": url,
        "rendered_media_candidates": media[:150],
        "rendered_text": collect_page_text(soup, url)["text"][:50000],
        "notes": [
            "Candidate URLs are NOT yet downloaded or visually approved.",
            "No social login or access bypass.",
        ],
    }
    path = project_path / "research/browser-gallery-candidates.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf8")
    result: dict[str, Any] = {
        "saved_to": str(path),
        "candidate_count": len(out["rendered_media_candidates"]),
    }
    if download:
        manifest = project_path / "research/asset-manifest.json"
        rows: list[dict[str, Any]] = (
            json.loads(manifest.read_text(encoding="utf8")) if manifest.exists() else []
        )
        seen: dict[str, str] = {
            str(r["sha256"]): str(r["file"]) for r in rows if r.get("sha256") and r.get("file")
        }
        known_urls = {r.get("url") for r in rows}
        added: list[dict[str, Any]] = []
        total = 0
        with build_collector_session(
            user_agent="PetSiteResearchBot/0.2 (+gallery-review)"
        ) as sess:
            robots: dict[str, RobotFileParser | bool | None] = {}
            for item in out["rendered_media_candidates"][:max_files]:
                if item["url"] in known_urls:
                    continue
                if total >= 60 * 1024 * 1024:
                    break
                row = download_one(
                    sess,
                    item,
                    project_path / "assets/website",
                    seen,
                    robots,
                    remaining_bytes=60 * 1024 * 1024 - total,
                )
                total += int(row.get("bytes", 0))
                rows.append(row)
                added.append(row)
                known_urls.add(item["url"])
        manifest.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf8")
        result["assets_saved"] = sum(r["status"] == "downloaded" for r in added)
        result["bytes_downloaded"] = total
        result["blocked_or_failed"] = sum(
            r["status"] not in ("downloaded", "duplicate") for r in added
        )
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--no-download", action="store_true")
    a = ap.parse_args()
    print(json.dumps(render_gallery(a.url, a.project, download=not a.no_download), indent=2))


if __name__ == "__main__":
    main()
