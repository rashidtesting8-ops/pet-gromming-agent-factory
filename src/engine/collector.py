"""Evidence-preserving website asset/content collector for small business previews.

Public website pages only; no authentication, platform scraping, or copyrighted
asset licensing claims. Designed for locally controlled sites / authorized reviews.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import ipaddress
import json
import mimetypes
import re
import socket
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Tag
from PIL import Image, UnidentifiedImageError

from engine.contracts import atomic_write_bytes, atomic_write_json

AGENT = "PetSiteResearchBot"
USER_AGENT = "PetSiteResearchBot/0.2 (+respectful-preview-audit)"
DEFAULT_MAX_MEDIA = 80
MAX_SITE_BYTES = 140 * 1024 * 1024
MEDIA_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".avif",
    ".gif",
    ".svg",
    ".mp4",
    ".webm",
    ".mov",
}
MEDIA_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}
BAD_PAGE_HINTS = ("logout", "cart", "checkout", "admin", "wp-login", "/feed")
PAGE_HINTS = (
    "gallery",
    "photo",
    "portfolio",
    "about",
    "service",
    "price",
    "review",
    "faq",
    "contact",
    "policy",
    "book",
)


def now() -> str:
    return datetime.now(UTC).isoformat()


def slugify(value: str) -> str:
    val = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return val[:65] or "website"


def safe_url(url: str, allow_private: bool = False) -> str:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Only absolute HTTP(S) URLs are allowed")
    if p.username or p.password:
        raise ValueError("Embedded credentials are not permitted")
    if allow_private:
        return url
    port = p.port or (443 if p.scheme == "https" else 80)
    ips = socket.getaddrinfo(p.hostname, port, type=socket.SOCK_STREAM)
    if not ips or any(not ipaddress.ip_address(result[4][0]).is_global for result in ips):
        raise ValueError("Non-public address blocked")
    return url


def response_get(
    session: requests.Session,
    url: str,
    *,
    allow_private: bool = False,
    stream: bool = False,
) -> requests.Response:
    # Validate every redirect hop to block SSRF via redirects.
    for _ in range(6):
        safe_url(url, allow_private=allow_private)
        response = session.get(url, timeout=(7, 18), stream=stream, allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308):
            nxt = response.headers.get("Location")
            response.close()
            if not nxt:
                raise RuntimeError("Redirect without Location")
            url = urljoin(url, nxt)
            continue
        return response
    raise RuntimeError("Too many redirects")


def normalize_page_url(url: str) -> str:
    return urldefrag(url)[0].rstrip("/") or url


def same_site(a: str, b: str) -> bool:
    ah = (urlparse(a).hostname or "").lower().removeprefix("www.")
    bh = (urlparse(b).hostname or "").lower().removeprefix("www.")
    return ah == bh


def robots_allowed(
    session: requests.Session,
    url: str,
    cache: dict[str, RobotFileParser | bool | None],
    *,
    allow_private: bool = False,
) -> bool:
    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    if origin not in cache:
        rp = RobotFileParser()
        rp.set_url(origin + "/robots.txt")
        try:
            r = response_get(
                session, origin + "/robots.txt", allow_private=allow_private, stream=True
            )
            try:
                if r.status_code in (401, 403) or r.status_code >= 500:
                    cache[origin] = False
                elif r.status_code in (404, 410):
                    cache[origin] = None
                elif r.ok:
                    text = bytearray()
                    for chunk in r.iter_content(65536):
                        text.extend(chunk)
                        if len(text) > 1024 * 1024:
                            raise ValueError("robots.txt too large")
                    rp.parse(text.decode("utf8", errors="replace").splitlines())
                    cache[origin] = rp
                else:
                    cache[origin] = False
            finally:
                r.close()
        except (requests.RequestException, ValueError, RuntimeError):
            cache[origin] = False
    rp_entry = cache[origin]
    if rp_entry is None:
        return True
    if isinstance(rp_entry, RobotFileParser):
        return rp_entry.can_fetch(AGENT, url)
    return False


def choose_srcset(srcset: str) -> str:
    picks: list[tuple[float, str]] = []
    for item in srcset.split(","):
        bits = item.strip().split()
        if bits:
            w = 1.0
            if len(bits) > 1:
                try:
                    w = float(bits[1][:-1]) * (1000.0 if bits[1].endswith("x") else 1.0)
                except ValueError:
                    pass
            picks.append((w, bits[0]))
    return max(picks, default=(0.0, ""))[1]


def candidate_url(raw: str, base: str) -> str | None:
    if not raw or raw.startswith(("data:", "blob:", "javascript:", "mailto:")):
        return None
    return urljoin(base, raw.strip())


def _attr_str(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(x) for x in value)
    return str(value or "")


def grab_media(soup: BeautifulSoup, page_url: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    keys = ("src", "data-src", "data-lazy-src", "data-original", "data-image", "poster")
    for tag in soup.find_all(["img", "source", "video", "a", "meta"]):
        vals: list[str] = []
        for k in keys:
            if tag.has_attr(k):
                vals.append(_attr_str(tag.get(k)))
        for k in ("srcset", "data-srcset"):
            if tag.has_attr(k):
                vals.append(choose_srcset(_attr_str(tag.get(k))))
        if tag.name == "a" and tag.has_attr("href"):
            href_str = _attr_str(tag.get("href"))
            if Path(urlparse(href_str).path.lower()).suffix in MEDIA_EXTENSIONS:
                vals.append(href_str)
        if tag.name == "meta":
            prop = _attr_str(tag.get("property")).lower()
            if prop in ("og:image", "og:video", "twitter:image"):
                vals.append(_attr_str(tag.get("content")))
        for raw in vals:
            url = candidate_url(raw, page_url)
            if url:
                found.append(
                    {
                        "url": url,
                        "source_page": page_url,
                        "alt": _attr_str(tag.get("alt")),
                        "discovery": tag.name,
                    }
                )
    # Inline CSS assets such as branded background images.
    for tag in soup.select("[style]"):
        style_val = _attr_str(tag.get("style"))
        for raw in re.findall(r"url\(\s*['\"]?([^)'\"]+)", style_val, re.I):
            url = candidate_url(raw, page_url)
            if url:
                found.append(
                    {"url": url, "source_page": page_url, "alt": "", "discovery": "inline-css"}
                )
    return found


def collect_page_text(soup: BeautifulSoup, url: str) -> dict[str, str]:
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = "\n".join(t.strip() for t in soup.stripped_strings if t.strip())
    text = re.sub(r"\n{3,}", "\n\n", text)
    return {"url": url, "text": text[:90000]}


def media_type(content_type: str, url: str) -> tuple[str | None, str | None]:
    ctype = content_type.split(";")[0].strip().lower()
    if ctype in MEDIA_TYPES:
        return ctype, MEDIA_TYPES[ctype]
    ext = Path(urlparse(url).path.lower()).suffix
    if ext in MEDIA_EXTENSIONS:
        guessed = mimetypes.guess_type("x" + ext)[0] or "application/octet-stream"
        return guessed, ext
    return None, None


def download_one(
    session: requests.Session,
    candidate: dict[str, Any],
    folder: Path,
    seen_sha: dict[str, str],
    robots_cache: dict[str, RobotFileParser | bool | None],
    *,
    allow_private: bool = False,
    remaining_bytes: int | None = None,
) -> dict[str, Any]:
    url = str(candidate["url"])
    if not robots_allowed(session, url, robots_cache, allow_private=allow_private):
        return {**candidate, "status": "blocked_by_robots"}
    res: requests.Response | None = None
    try:
        res = response_get(session, url, allow_private=allow_private, stream=True)
        res.raise_for_status()
        ctype, ext = media_type(res.headers.get("content-type", ""), res.url)
        if not ctype or not ext:
            return {**candidate, "status": "not_recognized_media"}
        limit = 40 * 1024 * 1024 if ctype.startswith("video/") else 16 * 1024 * 1024
        if remaining_bytes is not None:
            limit = min(limit, remaining_bytes)
        content_len = res.headers.get("Content-Length", "")
        if content_len.isdigit() and int(content_len) > limit:
            return {**candidate, "status": "too_large", "limit_bytes": limit}
        blob = bytearray()
        for chunk in res.iter_content(chunk_size=65536):
            blob.extend(chunk)
            if len(blob) > limit:
                return {**candidate, "status": "too_large", "limit_bytes": limit}
        if not blob:
            return {**candidate, "status": "empty"}
        dimensions: list[int] | None = None
        if ctype.startswith("image/") and ext != ".svg":
            try:
                with Image.open(io.BytesIO(blob)) as im:
                    dimensions = [im.width, im.height]
            except (UnidentifiedImageError, OSError, ValueError):
                return {**candidate, "status": "invalid_image"}
        sha = hashlib.sha256(blob).hexdigest()
        if sha in seen_sha:
            return {**candidate, "status": "duplicate", "same_as": seen_sha[sha], "sha256": sha}
        source_hint = Path(unquote(urlparse(res.url).path)).stem
        fname = slugify(str(candidate.get("alt", "")) or source_hint)[:36] + "-" + sha[:12] + ext
        out = folder / fname
        atomic_write_bytes(out, bytes(blob))
        rel = "assets/website/" + fname
        seen_sha[sha] = rel
        return {
            **candidate,
            "status": "downloaded",
            "file": rel,
            "bytes": len(blob),
            "sha256": sha,
            "dimensions": dimensions,
            "mime": ctype,
            "captured_at": now(),
            "rights_confirmed_for_preview": False,
        }
    except (requests.RequestException, RuntimeError, ValueError, OSError) as e:
        return {**candidate, "status": "failed", "error": str(e)[:240]}
    finally:
        if res is not None:
            res.close()


def collect(
    site_url: str,
    base_folder: str | Path,
    max_pages: int = 25,
    max_media: int = DEFAULT_MAX_MEDIA,
    *,
    allow_private: bool = False,
) -> dict[str, Any]:
    if not 1 <= max_pages <= 40 or not 1 <= max_media <= 120:
        raise ValueError("max_pages must be 1..40 and max_media 1..120")
    safe_url(site_url, allow_private=allow_private)
    parsed = urlparse(site_url)
    name = slugify((parsed.hostname or "website").removeprefix("www."))
    folder = Path(base_folder) / name
    folder.mkdir(parents=True, exist_ok=True)
    for sub in (
        "assets/website",
        "assets/instagram",
        "assets/facebook",
        "assets/optimized",
        "research",
        "design",
        "qa",
        "website",
        "delivery",
    ):
        (folder / sub).mkdir(parents=True, exist_ok=True)

    sess = requests.Session()
    sess.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,image/*;q=0.9,*/*;q=0.8",
        }
    )
    queue: deque[str] = deque([site_url])
    seen_pages: set[str] = set()
    candidates: dict[str, dict[str, str]] = {}
    pages: list[dict[str, Any]] = []
    social: dict[str, list[str]] = {"instagram": [], "facebook": []}
    problems: list[dict[str, str]] = []
    robots: dict[str, RobotFileParser | bool | None] = {}
    deadline = time.monotonic() + 210
    while queue and len(seen_pages) < max_pages:
        if time.monotonic() > deadline:
            problems.append({"reason": "crawl_time_limit"})
            break
        page = normalize_page_url(queue.popleft())
        if (
            page in seen_pages
            or not same_site(page, site_url)
            or any(x in page.lower() for x in BAD_PAGE_HINTS)
        ):
            continue
        seen_pages.add(page)
        if not robots_allowed(sess, page, robots, allow_private=allow_private):
            problems.append({"url": page, "reason": "robots_disallow"})
            continue
        try:
            res = response_get(sess, page, allow_private=allow_private, stream=True)
            try:
                res.raise_for_status()
                if "html" not in res.headers.get("content-type", "").lower():
                    continue
                payload = bytearray()
                for chunk in res.iter_content(65536):
                    payload.extend(chunk)
                    if len(payload) > 4 * 1024 * 1024:
                        break
                if len(payload) > 4 * 1024 * 1024:
                    problems.append({"url": page, "reason": "html_too_large"})
                    continue
                encoding = res.encoding or "utf8"
                html = payload.decode(encoding, errors="replace")
            finally:
                res.close()
            soup = BeautifulSoup(html, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            description_tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
            description = (
                _attr_str(description_tag.get("content"))
                if isinstance(description_tag, Tag)
                else ""
            )
            media = grab_media(soup, res.url)
            for m in media:
                candidates.setdefault(m["url"], m)
            links: list[str] = []
            for a in soup.select("a[href]"):
                target = candidate_url(_attr_str(a.get("href")), res.url)
                if not target:
                    continue
                host = (urlparse(target).hostname or "").lower()
                if (
                    host in ("instagram.com", "www.instagram.com")
                    and target not in social["instagram"]
                ):
                    social["instagram"].append(target)
                if (
                    host
                    in ("facebook.com", "www.facebook.com", "m.facebook.com", "fb.com", "fb.watch")
                    and target not in social["facebook"]
                ):
                    social["facebook"].append(target)
                if (
                    same_site(target, site_url)
                    and Path(urlparse(target).path.lower()).suffix not in MEDIA_EXTENSIONS
                ):
                    links.append(normalize_page_url(target))
            links = sorted(
                set(links), key=lambda u: (not any(k in u.lower() for k in PAGE_HINTS), u)
            )
            for link in links:
                if link not in seen_pages and link not in queue:
                    queue.append(link)
            body_page = collect_page_text(soup, res.url)
            pages.append(
                {
                    "url": res.url,
                    "title": title,
                    "description": description,
                    "text": body_page["text"],
                    "media_candidates": len(media),
                }
            )
        except (requests.RequestException, ValueError, RuntimeError) as e:
            problems.append({"url": page, "reason": str(e)[:240]})
    assets: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    total_bytes = 0
    for item in list(candidates.values())[:max_media]:
        if time.monotonic() > deadline:
            assets.append({**item, "status": "skipped_crawl_time_limit"})
            continue
        if total_bytes >= MAX_SITE_BYTES:
            assets.append({**item, "status": "skipped_site_storage_limit"})
            continue
        row = download_one(
            sess,
            item,
            folder / "assets/website",
            hashes,
            robots,
            allow_private=allow_private,
            remaining_bytes=MAX_SITE_BYTES - total_bytes,
        )
        total_bytes += int(row.get("bytes", 0))
        assets.append(row)
    status: dict[str, Any] = {
        "site_url": site_url,
        "captured_at": now(),
        "project_folder": str(folder),
        "pages_crawled": len(pages),
        "asset_candidates": len(candidates),
        "assets_saved": sum(a["status"] == "downloaded" for a in assets),
        "asset_duplicates": sum(a["status"] == "duplicate" for a in assets),
        "website_media_bytes_this_run": total_bytes,
        "issues": problems,
        "notes": [
            "Public website HTML only; JavaScript-injected content may need browser fallback.",
            (
                "Instagram/Facebook content is not silently scraped. "
                "Their URLs are recorded for authorized collection."
            ),
            "All factual business claims require later verification before publication.",
        ],
    }
    atomic_write_json(folder / "research/pages.json", pages, ensure_ascii=False)
    atomic_write_json(folder / "research/asset-manifest.json", assets, ensure_ascii=False)
    atomic_write_json(
        folder / "research/social-sources.json",
        {**social, "collection_status": "needs_authorized_collection_or_manual_upload"},
        ensure_ascii=True,
    )
    atomic_write_json(folder / "research/run-summary.json", status, ensure_ascii=True)
    return status


def main() -> None:
    p = argparse.ArgumentParser(description="Pet grooming asset collector")
    p.add_argument("url", help="Full public business website URL")
    p.add_argument("--output", default="./projects")
    p.add_argument("--max-pages", type=int, default=25)
    p.add_argument("--max-media", type=int, default=DEFAULT_MAX_MEDIA)
    a = p.parse_args()
    print(json.dumps(collect(a.url, a.output, a.max_pages, a.max_media), indent=2))


if __name__ == "__main__":
    main()
