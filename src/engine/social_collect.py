"""Bounded, opt-in gallery-dl subprocess adapter for public Instagram/Facebook sources.

No logins, cookies, proxy rotation, or access-bypass features. gallery-dl runs
ONLY as an external subprocess and is never imported. When a platform requires
authentication, rate-limits, or breaks, return a review_needed result with a
classified reason and never raise to the caller.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

from engine.collector import MEDIA_TYPES, build_collector_session, response_get, safe_url

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}
ALLOWED = IMAGE_EXTENSIONS | {".mp4", ".webm", ".mov"}
SOCIAL_HOSTS = {
    "instagram": {"instagram.com", "www.instagram.com"},
    "facebook": {
        "facebook.com",
        "www.facebook.com",
        "m.facebook.com",
        "web.facebook.com",
        "fb.watch",
    },
}
MAX_ITEM_BYTES = 25 * 1024 * 1024
MAX_STAGING_BYTES = 150 * 1024 * 1024
MAX_PROJECT_BYTES = 300 * 1024 * 1024

_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(cookie|sessionid|csrftoken|authorization|bearer|password|token)\s*[:=]\s*\S+"),
)

_LOGIN_PATTERNS = (
    "login required",
    "login_required",
    "checkpoint_required",
    "401 unauthorized",
    "403 forbidden",
    "authentication required",
    "requires login",
    "private account",
    "not logged in",
    "sign in to continue",
    "redirect to login page",
    "/accounts/login",
    "cookies",
)

# gallery-dl argparse usage errors: our command line is wrong, not the platform.
_MISCONFIGURED_PATTERNS = (
    "unrecognized arguments",
    "error: argument",
    "usage: gallery-dl",
)

# Instagram answers anonymous profile lookups with HTTP 404 even for real accounts,
# so without a login we cannot tell "does not exist" from "login wall".
_NOT_FOUND_PATTERNS = (
    "requested user could not be found",
    "notfounderror",
)

_RATE_LIMIT_PATTERNS = (
    "429",
    "too many requests",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "please wait a few minutes",
    "throttl",
    "try again later",
)

_EXTRACTOR_BROKEN_PATTERNS = (
    "extractorerror",
    "unable to extract",
    "keyerror",
    "attributeerror",
    "typeerror",
    "jsondecodeerror",
    "parse error",
    "unexpected response",
    "traceback (most recent call last)",
    "unsupported url",
)


def cutoff_year(today: date | None = None) -> date:
    day = today or date.today()
    try:
        return day.replace(year=day.year - 1)
    except ValueError:  # Feb 29
        return day.replace(year=day.year - 1, day=28)


def check_social_url(platform: str, url: str) -> str:
    if platform not in SOCIAL_HOSTS:
        raise ValueError("Choose instagram or facebook")
    u = urlparse(url)
    if (
        u.scheme != "https"
        or u.username
        or u.password
        or (u.hostname or "").lower() not in SOCIAL_HOSTS[platform]
    ):
        raise ValueError(
            "Only public HTTPS Instagram/Facebook URLs on the expected platform are accepted"
        )
    return url


def folder_size(root: str | Path) -> int:
    root_path = Path(root)
    if not root_path.exists():
        return 0
    return sum(
        p.stat().st_size for p in root_path.rglob("*") if p.is_file() and not p.is_symlink()
    )


def file_safe(p: Path) -> bool:
    return (
        p.is_file()
        and not p.is_symlink()
        and p.suffix.lower() in ALLOWED
        and p.stat().st_size <= MAX_ITEM_BYTES
    )


def scrub_sensitive_text(text: str) -> str:
    """Remove any accidental cookie, session, or token values before logging or returning."""
    cleaned = text
    for pat in _SENSITIVE_PATTERNS:
        cleaned = pat.sub(r"\1=[REDACTED]", cleaned)
    return cleaned


def classify_social_failure(exit_code: int, output: str) -> str:
    """Classify gallery-dl failure output into a bounded failure reason."""
    lowered = (output or "").lower()
    if any(token in lowered for token in _MISCONFIGURED_PATTERNS):
        return "extractor_misconfigured"
    if any(token in lowered for token in _LOGIN_PATTERNS):
        return "login_required"
    if any(token in lowered for token in _RATE_LIMIT_PATTERNS):
        return "rate_limited"
    if any(token in lowered for token in _NOT_FOUND_PATTERNS):
        return "not_found_or_login_wall"
    if any(token in lowered for token in _EXTRACTOR_BROKEN_PATTERNS):
        return "extractor_broken"
    _ = exit_code
    return "unknown"


def _parse_real_timestamp(raw_val: Any) -> str | None:
    """Parse a real post timestamp from gallery-dl metadata into UTC ISO-8601 format."""
    if raw_val is None or isinstance(raw_val, bool):
        return None
    if isinstance(raw_val, int | float):
        if raw_val <= 0:
            return None
        try:
            return datetime.fromtimestamp(float(raw_val), tz=UTC).isoformat()
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(raw_val, str):
        text = raw_val.strip()
        if not text:
            return None
        if text.isdigit():
            val = int(text)
            if val > 0:
                try:
                    return datetime.fromtimestamp(float(val), tz=UTC).isoformat()
                except (OSError, OverflowError, ValueError):
                    return None
        normalized = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            else:
                dt = dt.astimezone(UTC)
            return dt.isoformat()
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, fmt).replace(tzinfo=UTC)
                return dt.isoformat()
            except ValueError:
                continue
    return None


def derive_post_metadata(meta: dict[str, Any], *, fallback_url: str) -> dict[str, Any]:
    """Derive post_date, post_date_verified, original_post_url, and author from metadata."""
    post_date: str | None = None
    for key in ("date", "post_date", "timestamp", "created_at", "taken_at"):
        if key in meta:
            parsed = _parse_real_timestamp(meta.get(key))
            if parsed is not None:
                post_date = parsed
                break

    original_post_url: str | None = None
    for url_key in ("post_url", "original_post_url", "webpage_url"):
        candidate = meta.get(url_key)
        if isinstance(candidate, str) and candidate.startswith("https://"):
            original_post_url = candidate
            break
    if original_post_url is None and isinstance(meta.get("post_shortcode"), str):
        shortcode = meta["post_shortcode"].strip("/")
        if shortcode and "instagram.com" in fallback_url:
            original_post_url = f"https://www.instagram.com/p/{shortcode}/"

    author: str | None = None
    for author_key in ("author", "username", "owner", "fullname", "user"):
        candidate = meta.get(author_key)
        if isinstance(candidate, str) and candidate.strip():
            author = candidate.strip()
            break
        if isinstance(candidate, dict):
            nested = candidate.get("username") or candidate.get("name")
            if isinstance(nested, str) and nested.strip():
                author = nested.strip()
                break

    return {
        "post_date": post_date,
        "post_date_verified": post_date is not None,
        "original_post_url": original_post_url or fallback_url,
        "source_post_url": original_post_url,
        "author": author,
    }


def parse_dump_json_metadata(raw_output: str) -> list[dict[str, Any]]:
    """Extract per-item metadata dictionaries from gallery-dl --dump-json output."""
    text = (raw_output or "").strip()
    if not text:
        return []

    records: list[dict[str, Any]] = []
    shared_context: dict[str, Any] = {}

    def _collect_from_parsed(parsed: Any) -> None:
        if isinstance(parsed, dict):
            records.append(dict(parsed))
            return
        if isinstance(parsed, list):
            for entry in parsed:
                if isinstance(entry, dict):
                    records.append(dict(entry))
                elif isinstance(entry, list) and entry:
                    code = entry[0]
                    dicts = [item for item in entry[1:] if isinstance(item, dict)]
                    if code == 2 and dicts:
                        shared_context.update(dicts[-1])
                    elif code == 3 and dicts:
                        merged = {**shared_context, **dicts[-1]}
                        records.append(merged)

    try:
        _collect_from_parsed(json.loads(text))
    except json.JSONDecodeError:
        for line in text.splitlines():
            line_str = line.strip()
            if not line_str or not (line_str.startswith("{") or line_str.startswith("[")):
                continue
            try:
                _collect_from_parsed(json.loads(line_str))
            except json.JSONDecodeError:
                continue

    return records


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _atomic_write_text(target: Path, content: str) -> None:
    _atomic_write_bytes(target, content.encode("utf-8"))


def strip_image_metadata(src: Path, dest: Path) -> bytes:
    """Create an optimized copy of an image with all EXIF/GPS metadata removed."""
    with Image.open(src) as im:
        fmt = (im.format or "PNG").upper()
        clean = Image.new(im.mode, im.size)
        clean.putdata(list(im.getdata()))
        if "transparency" in im.info and fmt in {"PNG", "GIF", "WEBP"}:
            clean.info["transparency"] = im.info["transparency"]
        from io import BytesIO

        buf = BytesIO()
        save_kwargs: dict[str, Any] = {}
        if fmt in {"JPEG", "JPG"}:
            fmt = "JPEG"
            if clean.mode not in {"RGB", "L", "CMYK"}:
                clean = clean.convert("RGB")
            save_kwargs["quality"] = 90
            save_kwargs["optimize"] = True
        clean.save(buf, format=fmt, **save_kwargs)
        data = buf.getvalue()
        _atomic_write_bytes(dest, data)
        return data


def _build_gallery_dl_cmd(
    *,
    executable: str,
    cutoff_date: str,
    max_files: int,
    http_timeout: int,
    sleep_request: float,
    sleep_seconds: float,
    archive_path: Path,
    stage: Path,
    platform: str,
    url: str,
    dry_run: bool,
) -> list[str]:
    cmd = [
        executable,
        "--config-ignore",
        "--no-input",
        "--no-colors",
    ]
    if dry_run:
        cmd.append("--dump-json")
    cutoff = date.fromisoformat(cutoff_date)
    # gallery-dl has no --date-after flag. Use a filter expression on the post `date`
    # metadata; feeds are newest-first, so abort() stops at the first post older than
    # the cutoff instead of walking the whole profile history.
    date_filter = (
        f"date >= datetime({cutoff.year}, {cutoff.month}, {cutoff.day}) or abort()"
    )
    cmd.extend(
        [
            "--filter",
            date_filter,
            "--range",
            f"1-{max_files}",
            "--filesize-max",
            "25M",
            "--http-timeout",
            str(http_timeout),
            "--retries",
            "1",
            "--sleep-request",
            str(sleep_request),
            "--sleep",
            str(sleep_seconds),
            "--download-archive",
            str(archive_path),
            "--directory",
            str(stage),
            # Only follow child extractors of the requested platform (no external hosts).
            "-o",
            f"whitelist={platform}",
            url,
        ]
    )
    return cmd


_ALT_META_RE = re.compile(
    r"^(?:Photo|Video|Clip|Reel)\s+by\s+(?P<author>.+?)\s+on\s+"
    r"(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})(?:\.|$)",
    re.IGNORECASE,
)


def parse_instagram_alt_metadata(alt_text: str) -> dict[str, Any]:
    """Parse real post date and author from Instagram's accessibility alt text when present."""
    cleaned = (alt_text or "").strip()
    if not cleaned:
        return {"author": None, "post_date": None, "post_date_verified": False}
    match = _ALT_META_RE.match(cleaned)
    if not match:
        return {"author": None, "post_date": None, "post_date_verified": False}
    author = match.group("author").strip() or None
    raw_date = re.sub(r"\s+", " ", match.group("date").strip())
    post_date: str | None = None
    try:
        dt = datetime.strptime(raw_date, "%B %d, %Y").replace(tzinfo=UTC)
        post_date = dt.isoformat()
    except ValueError:
        post_date = None
    return {
        "author": author,
        "post_date": post_date,
        "post_date_verified": post_date is not None,
    }


def _kill_process_tree(proc: subprocess.Popen[bytes] | subprocess.Popen[str]) -> None:
    """Terminate a subprocess and its spawned descendants (Windows exe shims spawn children)."""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except Exception:
            pass
    if proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except Exception:
                pass


def _execute_subprocess(
    cmd: list[str],
    stage: Path,
    *,
    timeout: int,
    runner: Callable[[list[str], Path], tuple[int, str]] | None,
) -> tuple[int, str]:
    if runner is not None:
        ret, out = runner(cmd, stage)
        return ret, scrub_sensitive_text(out or "")

    # Store output log OUTSIDE `stage` so a slow child handle release on Windows never
    # raises WinError 32 or blocks `TemporaryDirectory(stage)` cleanup / partial recovery.
    fd, tmp_log_name = tempfile.mkstemp(prefix="pet-social-log-", suffix=".txt")
    os.close(fd)
    log = Path(tmp_log_name)
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    try:
        with log.open("wb") as handle:
            proc = subprocess.Popen(
                cmd,
                stdout=handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=str(stage),
                shell=False,
                **popen_kwargs,
            )
            started = time.monotonic()
            exceeded = False
            while proc.poll() is None:
                if (time.monotonic() - started) > timeout or folder_size(stage) > MAX_STAGING_BYTES:
                    exceeded = True
                    _kill_process_tree(proc)
                    break
                time.sleep(0.25)
            ret = 124 if exceeded else (proc.returncode or 0)
        raw_text = log.read_text(encoding="utf8", errors="replace")
        return ret, scrub_sensitive_text(raw_text)
    finally:
        for _ in range(5):
            try:
                log.unlink(missing_ok=True)
                break
            except OSError:
                time.sleep(0.05)


def _match_metadata_for_file(
    src: Path,
    index: int,
    metadata_records: list[dict[str, Any]],
) -> dict[str, Any]:
    sidecar = src.with_suffix(src.suffix + ".json")
    if sidecar.is_file():
        try:
            loaded = json.loads(sidecar.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        except (OSError, json.JSONDecodeError):
            pass

    stem = src.stem.lower()
    name = src.name.lower()
    for record in metadata_records:
        rec_filename = str(record.get("filename") or "").lower()
        rec_ext = str(record.get("extension") or "").lower().lstrip(".")
        rec_full = f"{rec_filename}.{rec_ext}" if rec_filename and rec_ext else rec_filename
        if rec_filename and (rec_filename == stem or rec_full == name):
            return record

    if index < len(metadata_records):
        return metadata_records[index]
    if len(metadata_records) == 1:
        return metadata_records[0]
    return {}


def _download_public_image_bytes(
    session: Any,
    raw_url: str,
) -> tuple[bytes, str] | None:
    """Download a single public CDN image via SSRF-safe session, bounded by MAX_ITEM_BYTES."""
    safe_url(raw_url)
    res = response_get(session, raw_url, allow_private=False, stream=True)
    try:
        res.raise_for_status()
        ctype = res.headers.get("content-type", "").split(";")[0].strip().lower()
        ext = MEDIA_TYPES.get(ctype) or Path(urlparse(res.url).path.lower()).suffix
        if ext not in IMAGE_EXTENSIONS:
            ext = ".jpg"
        blob = bytearray()
        for chunk in res.iter_content(chunk_size=65536):
            blob.extend(chunk)
            if len(blob) > MAX_ITEM_BYTES:
                return None
        if not blob:
            return None
        return bytes(blob), ext
    finally:
        res.close()


def _extract_instagram_embed_image(
    session: Any,
    post_url: str,
) -> tuple[str | None, bool]:
    """Fetch public `/embed/captioned/` page for high-resolution image URL without login."""
    clean_base = post_url.split("?")[0].split("#")[0].rstrip("/")
    match = re.search(r"/(p|reel)/([A-Za-z0-9_-]+)$", clean_base)
    if not match:
        return None, False
    embed_url = f"https://www.instagram.com/{match.group(1)}/{match.group(2)}/embed/captioned/"
    safe_url(embed_url)
    res = response_get(session, embed_url, allow_private=False)
    try:
        if "/accounts/login" in res.url.lower():
            return None, True
        if res.status_code in (401, 403, 404):
            return None, False
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        img = soup.select_one("img.EmbeddedMediaImage")
        if img is not None:
            src = img.get("src")
            if isinstance(src, str) and src.startswith("https://"):
                return src, False
        return None, False
    finally:
        res.close()


def _fetch_public_instagram_items(
    url: str,
    *,
    max_files: int,
    http_timeout: int,
) -> dict[str, Any]:
    """Read-only public fallback for Instagram profiles/posts when gallery-dl API 404s.

    Uses zero logins, cookies, credentials, CAPTCHA evasion, or identity rotation.
    """
    check_social_url("instagram", url)
    safe_url(url)
    # Instagram /embed/captioned/ returns static SSR HTML containing EmbeddedMediaImage
    # only for standard desktop "Mozilla/5.0" UA (full Chrome tokens trigger CSR shell).
    session = build_collector_session(user_agent="Mozilla/5.0")
    parsed = urlparse(url)
    path_clean = parsed.path.rstrip("/")
    items: list[dict[str, Any]] = []

    # Case 1: Single public post or reel URL -> use public /embed/captioned/ endpoint.
    if re.search(r"/(?:p|reel)/[A-Za-z0-9_-]+$", path_clean):
        try:
            embed_img_url, login_hit = _extract_instagram_embed_image(session, url)
            if login_hit:
                return {"login_required": True, "items": []}
            if embed_img_url:
                downloaded = _download_public_image_bytes(session, embed_img_url)
                if downloaded is not None:
                    blob, ext = downloaded
                    items.append(
                        {
                            "post_url": url.split("?")[0],
                            "image_bytes": blob,
                            "extension": ext,
                            "author": None,
                            "post_date": None,
                            "post_date_verified": False,
                        }
                    )
        except Exception as exc:
            return {"login_required": False, "items": [], "error": str(exc)}
        return {"login_required": False, "items": items}

    # Case 2: Public profile page via ephemeral unauthenticated Playwright browser.
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        return {"login_required": False, "items": [], "error": str(exc)}

    from engine.browser_gallery import verify_browser_url

    handle = path_clean.strip("/").split("/")[0] if path_clean.strip("/") else None
    candidates: list[dict[str, Any]] = []
    login_required = False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})

                verified_hosts: set[str] = set()

                def _ssrf_guard(route: Any) -> None:
                    try:
                        req_url = route.request.url
                        parsed_req = urlparse(req_url)
                        host_key = f"{parsed_req.scheme}:{parsed_req.netloc}"
                        if host_key not in verified_hosts:
                            verify_browser_url(req_url)
                            verified_hosts.add(host_key)
                        route.continue_()
                    except Exception:
                        route.abort()

                page.route("**/*", _ssrf_guard)
                nav_timeout_ms = min(max(http_timeout, 15), 45) * 1000
                page.goto(url, wait_until="domcontentloaded", timeout=nav_timeout_ms)
                try:
                    page.wait_for_selector("a[href*='/p/'], a[href*='/reel/']", timeout=15000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)

                if "/accounts/login" in page.url.lower():
                    login_required = True
                else:
                    anchors = page.locator("a[href*='/p/'], a[href*='/reel/']").all()
                    if not anchors:
                        body_lower = (page.inner_text("body") or "").lower()
                        if any(
                            tok in body_lower
                            for tok in ("this account is private", "log in to continue", "sign up")
                        ):
                            login_required = True
                    seen_hrefs: set[str] = set()
                    for anchor in anchors:
                        if len(candidates) >= max_files:
                            break
                        href = anchor.get_attribute("href")
                        if not href:
                            continue
                        full_post_url = urljoin("https://www.instagram.com/", href).split("?")[0]
                        if full_post_url in seen_hrefs:
                            continue
                        seen_hrefs.add(full_post_url)
                        img_loc = anchor.locator("img").first
                        thumb_src = img_loc.get_attribute("src") if img_loc.count() else None
                        alt_text = img_loc.get_attribute("alt") if img_loc.count() else ""
                        alt_meta = parse_instagram_alt_metadata(alt_text or "")
                        candidates.append(
                            {
                                "post_url": full_post_url,
                                "thumb_src": thumb_src,
                                "author": alt_meta["author"] or handle,
                                "post_date": alt_meta["post_date"],
                                "post_date_verified": alt_meta["post_date_verified"],
                            }
                        )
            finally:
                browser.close()
    except Exception as exc:
        return {"login_required": False, "items": [], "error": str(exc)}

    if login_required and not candidates:
        return {"login_required": True, "items": []}

    for cand in candidates:
        if len(items) >= max_files:
            break
        img_url: str | None = None
        try:
            embed_url, _ = _extract_instagram_embed_image(session, str(cand["post_url"]))
            img_url = embed_url or cand.get("thumb_src")
        except Exception:
            img_url = cand.get("thumb_src")
        if not isinstance(img_url, str) or not img_url.startswith("https://"):
            continue
        try:
            downloaded = _download_public_image_bytes(session, img_url)
        except Exception:
            continue
        if downloaded is None:
            continue
        blob, ext = downloaded
        items.append(
            {
                "post_url": cand["post_url"],
                "image_bytes": blob,
                "extension": ext,
                "author": cand["author"],
                "post_date": cand["post_date"],
                "post_date_verified": cand["post_date_verified"],
            }
        )
        time.sleep(0.25)

    return {"login_required": False, "items": items}


def _persist_social_media_blob(
    *,
    blob: bytes,
    ext: str,
    is_image: bool,
    platform: str,
    project_path: Path,
    dest: Path,
    optimized_dest: Path,
    source_profile_url: str,
    derived: dict[str, Any],
    cutoff_date: str,
    known_hashes: set[str],
) -> tuple[dict[str, Any] | None, str]:
    """Validate, EXIF-strip, deduplicate, and persist a single social asset."""
    if len(blob) > MAX_ITEM_BYTES or not blob:
        return None, "corrupt"
    if is_image:
        try:
            with Image.open(io.BytesIO(blob)) as im:
                im.verify()
        except (UnidentifiedImageError, OSError, ValueError):
            return None, "corrupt"

    sha = hashlib.sha256(blob).hexdigest()
    if sha in known_hashes:
        return None, "duplicate"

    if derived.get("post_date_verified") and isinstance(derived.get("post_date"), str):
        post_day = datetime.fromisoformat(derived["post_date"]).date()
        if post_day < date.fromisoformat(cutoff_date):
            return None, "old"

    name = f"{platform}-{sha[:16]}{ext.lower()}"
    target = dest / name
    _atomic_write_bytes(target, blob)

    optimized_rel: str | None = None
    optimized_sha: str | None = None
    if is_image:
        opt_target = optimized_dest / name
        try:
            opt_bytes = strip_image_metadata(target, opt_target)
            optimized_rel = opt_target.relative_to(project_path).as_posix()
            optimized_sha = hashlib.sha256(opt_bytes).hexdigest()
        except (UnidentifiedImageError, OSError, ValueError):
            target.unlink(missing_ok=True)
            return None, "corrupt"

    captured_at = datetime.now(UTC).isoformat()
    known_hashes.add(sha)
    row = {
        "file": target.relative_to(project_path).as_posix(),
        "optimized_file": optimized_rel,
        "optimized_sha256": optimized_sha,
        "platform": platform,
        "source_profile_url": source_profile_url,
        "source_post_url": derived.get("source_post_url"),
        "original_post_url": derived.get("original_post_url") or source_profile_url,
        "author": derived.get("author"),
        "post_date": derived.get("post_date"),
        "post_date_verified": bool(derived.get("post_date_verified", False)),
        "date_filter_requested_after": cutoff_date,
        "sha256": sha,
        "bytes": len(blob),
        "captured_at": captured_at,
        "downloaded_at": captured_at,
        "rights_confirmed_for_preview": False,
        "ownership_verified": False,
    }
    return row, "added"


def collect_social(
    project: str | Path,
    platform: str,
    url: str,
    *,
    max_files: int = 40,
    days_limit: int = 365,
    timeout: int = 360,
    http_timeout: int = 20,
    sleep_request: float = 3.0,
    sleep_seconds: float = 1.0,
    executable: str = "gallery-dl",
    runner: Callable[[list[str], Path], tuple[int, str]] | None = None,
    i_have_permission: bool | None = None,
) -> dict[str, Any]:
    try:
        if i_have_permission is False or (i_have_permission is None and runner is None):
            return {
                "status": "review_needed",
                "reason": "permission_required",
                "files_added": 0,
            }
        check_social_url(platform, url)
        if not 1 <= max_files <= 80:
            raise ValueError("max_files must be 1..80")
        if not 1 <= days_limit <= 366:
            raise ValueError("days_limit must be 1..366")
        if not 10 <= timeout <= 600:
            raise ValueError("timeout must be 10..600")
        project_path = Path(project).resolve()
        if not project_path.is_dir() or not (project_path / "research").is_dir():
            raise ValueError("Existing project with research folder required")
        if folder_size(project_path) >= MAX_PROJECT_BYTES:
            return {
                "status": "review_needed",
                "reason": "project_storage_limit",
                "files_added": 0,
            }
        if shutil.which(executable) is None and runner is None:
            return {
                "status": "review_needed",
                "reason": "gallery_dl_not_installed",
                "files_added": 0,
            }

        cutoff = datetime.now(UTC).date().toordinal() - days_limit
        cutoff_date = date.fromordinal(cutoff).isoformat()
        dest = project_path / "assets" / platform
        optimized_dest = project_path / "assets" / "optimized"
        dest.mkdir(parents=True, exist_ok=True)
        optimized_dest.mkdir(parents=True, exist_ok=True)
        archive_path = project_path / "research" / f"social-archive-{platform}.txt"
        manifest_path = project_path / "research" / "social-media-manifest.json"
        existing: list[dict[str, Any]] = (
            json.loads(manifest_path.read_text(encoding="utf8"))
            if manifest_path.exists()
            else []
        )
        known_hashes = {str(x["sha256"]) for x in existing if "sha256" in x}
        rows: list[dict[str, Any]] = []
        corrupt_rejected = 0
        fallback_used = False

        with tempfile.TemporaryDirectory(prefix="pet-social-") as td:
            stage = Path(td)
            # Step 1: Dry-run metadata fetch (--dump-json) before downloading media
            dry_cmd = _build_gallery_dl_cmd(
                executable=executable,
                cutoff_date=cutoff_date,
                max_files=max_files,
                http_timeout=http_timeout,
                sleep_request=sleep_request,
                sleep_seconds=sleep_seconds,
                archive_path=archive_path,
                stage=stage,
                platform=platform,
                url=url,
                dry_run=True,
            )
            dry_ret, dry_out = _execute_subprocess(
                dry_cmd,
                stage,
                timeout=timeout,
                runner=runner,
            )
            metadata_records = parse_dump_json_metadata(dry_out)

            # Check if dry-run already failed cleanly with zero staged files/items
            staged_after_dry = [p for p in stage.rglob("*") if file_safe(p)]
            ret = dry_ret
            combined_msg = dry_out.strip()
            candidate_files: list[Path] = list(staged_after_dry)

            if not (dry_ret != 0 and not metadata_records and not staged_after_dry):
                # Step 2: Media download pass (skip only if a legacy test runner staged files)
                if staged_after_dry and runner is not None and not metadata_records:
                    ret, stderr = dry_ret, dry_out
                else:
                    dl_cmd = _build_gallery_dl_cmd(
                        executable=executable,
                        cutoff_date=cutoff_date,
                        max_files=max_files,
                        http_timeout=http_timeout,
                        sleep_request=sleep_request,
                        sleep_seconds=sleep_seconds,
                        archive_path=archive_path,
                        stage=stage,
                        platform=platform,
                        url=url,
                        dry_run=False,
                    )
                    ret, stderr = _execute_subprocess(
                        dl_cmd,
                        stage,
                        timeout=timeout,
                        runner=runner,
                    )

                combined_msg = (dry_out + "\n" + stderr).strip()
                candidate_files = [p for p in sorted(stage.rglob("*")) if file_safe(p)]

                for idx, src in enumerate(candidate_files):
                    if len(rows) >= max_files or folder_size(project_path) >= MAX_PROJECT_BYTES:
                        break
                    raw_meta = _match_metadata_for_file(src, idx, metadata_records)
                    derived = derive_post_metadata(raw_meta, fallback_url=url)
                    row, outcome = _persist_social_media_blob(
                        blob=src.read_bytes(),
                        ext=src.suffix.lower(),
                        is_image=src.suffix.lower() in IMAGE_EXTENSIONS,
                        platform=platform,
                        project_path=project_path,
                        dest=dest,
                        optimized_dest=optimized_dest,
                        source_profile_url=url,
                        derived=derived,
                        cutoff_date=cutoff_date,
                        known_hashes=known_hashes,
                    )
                    if outcome == "corrupt":
                        corrupt_rejected += 1
                    elif row is not None:
                        rows.append(row)

            # Compliant unauthenticated fallback when Instagram breaks gallery-dl's legacy API
            # (covers both Step-1 and Step-2 gallery-dl failures with zero code duplication).
            early_or_step2_reason = classify_social_failure(ret or dry_ret, combined_msg)
            if (
                not rows
                and not candidate_files
                and platform == "instagram"
                and runner is None
                and early_or_step2_reason in ("not_found_or_login_wall", "login_required")
            ):
                fallback_used = True
                pub = _fetch_public_instagram_items(
                    url, max_files=max_files, http_timeout=http_timeout
                )
                if pub.get("error"):
                    combined_msg = f"{combined_msg}\nfallback_error: {pub['error']}".strip()
                if pub.get("login_required"):
                    return {
                        "status": "review_needed",
                        "reason": "login_required",
                        "files_added": 0,
                        "platform": platform,
                        "cutoff": cutoff_date,
                        "project_bytes": folder_size(project_path),
                        "extractor_exit_code": ret or dry_ret,
                        "extractor_message": combined_msg[-500:],
                    }
                for item in pub.get("items", []):
                    if len(rows) >= max_files or folder_size(project_path) >= MAX_PROJECT_BYTES:
                        break
                    post_url = str(item.get("post_url") or url)
                    row, outcome = _persist_social_media_blob(
                        blob=bytes(item["image_bytes"]),
                        ext=str(item.get("extension") or ".jpg"),
                        is_image=True,
                        platform=platform,
                        project_path=project_path,
                        dest=dest,
                        optimized_dest=optimized_dest,
                        source_profile_url=url,
                        derived={
                            "source_post_url": post_url,
                            "original_post_url": post_url,
                            "author": item.get("author"),
                            "post_date": item.get("post_date"),
                            "post_date_verified": bool(item.get("post_date_verified", False)),
                        },
                        cutoff_date=cutoff_date,
                        known_hashes=known_hashes,
                    )
                    if outcome == "corrupt":
                        corrupt_rejected += 1
                    elif row is not None:
                        rows.append(row)
            elif dry_ret != 0 and not metadata_records and not candidate_files:
                return {
                    "status": "review_needed",
                    "reason": classify_social_failure(dry_ret, dry_out),
                    "files_added": 0,
                    "platform": platform,
                    "cutoff": cutoff_date,
                    "project_bytes": folder_size(project_path),
                    "extractor_exit_code": dry_ret,
                    "extractor_message": dry_out[-500:],
                }

        if rows:
            existing.extend(rows)
            _atomic_write_text(manifest_path, json.dumps(existing, indent=2))

        failure_reason: str | None = None
        if not rows and not fallback_used:
            if ret != 0 or dry_ret != 0:
                failure_reason = classify_social_failure(ret or dry_ret, combined_msg)
            elif corrupt_rejected > 0:
                failure_reason = "corrupt_or_empty_media"
            else:
                failure_reason = classify_social_failure(ret, combined_msg)

        result: dict[str, Any] = {
            "status": "collected_needs_review" if rows else "review_needed",
            "files_added": len(rows),
            "platform": platform,
            "cutoff": cutoff_date,
            "project_bytes": folder_size(project_path),
            "extractor_exit_code": ret,
            "extractor_message": combined_msg[-500:],
            "note": (
                "No platform login used. Confirm source post, published date, ownership "
                "and reuse permission before selecting any photo."
            ),
        }
        if fallback_used:
            result["collection_method"] = "public_instagram_browser_embed"
        if ret == 124 and rows:
            result["partial_timeout"] = True
        if failure_reason is not None:
            result["reason"] = failure_reason
        return result
    except Exception as exc:
        return {
            "status": "review_needed",
            "reason": classify_social_failure(1, str(exc)),
            "files_added": 0,
            "platform": platform,
            "extractor_message": scrub_sensitive_text(str(exc))[-500:],
        }


def run_cli(argv: Sequence[str] | None = None) -> dict[str, Any]:
    p = argparse.ArgumentParser()
    p.add_argument("--project", required=True)
    p.add_argument("--platform", required=True, choices=["instagram", "facebook"])
    p.add_argument("--url", required=True)
    p.add_argument("--max-files", type=int, default=40)
    p.add_argument("--days", type=int, default=365)
    p.add_argument(
        "--i-have-permission",
        action="store_true",
        default=False,
        help="Explicitly confirm permission to collect public social media for preview.",
    )
    args = p.parse_args(list(argv) if argv is not None else None)
    return collect_social(
        args.project,
        args.platform,
        args.url,
        max_files=args.max_files,
        days_limit=args.days,
        i_have_permission=bool(args.i_have_permission),
    )


def main() -> None:
    print(json.dumps(run_cli(), indent=2))


if __name__ == "__main__":
    main()
