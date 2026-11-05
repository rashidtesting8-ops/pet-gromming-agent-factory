"""Bounded, opt-in gallery-dl adapter for public Instagram/Facebook sources.

No logins, cookies, proxy rotation, or access-bypass features. When a platform
requires authentication, return a review-needed result rather than misreporting
success. Date windows are best effort when a platform lacks post-date metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image, UnidentifiedImageError

ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".mp4", ".webm", ".mov"}
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


def collect_social(
    project: str | Path,
    platform: str,
    url: str,
    *,
    max_files: int = 40,
    days_limit: int = 365,
    timeout: int = 180,
    executable: str = "gallery-dl",
    runner: Callable[[list[str], Path], tuple[int, str]] | None = None,
) -> dict[str, Any]:
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
        return {"status": "review_needed", "reason": "project_storage_limit", "files_added": 0}
    if shutil.which(executable) is None and runner is None:
        return {"status": "review_needed", "reason": "gallery_dl_not_installed", "files_added": 0}
    cutoff = datetime.now(UTC).date().toordinal() - days_limit
    cutoff_date = date.fromordinal(cutoff).isoformat()
    dest = project_path / "assets" / platform
    dest.mkdir(parents=True, exist_ok=True)
    manifest_path = project_path / "research" / "social-media-manifest.json"
    existing: list[dict[str, Any]] = (
        json.loads(manifest_path.read_text(encoding="utf8")) if manifest_path.exists() else []
    )
    known_hashes = {str(x["sha256"]) for x in existing if "sha256" in x}
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="pet-social-") as td:
        stage = Path(td)
        # Ignore ambient gallery-dl configuration: no browser cookies or user credentials.
        cmd = [
            executable,
            "--config-ignore",
            "--no-input",
            "--no-colors",
            "--date-after",
            cutoff_date,
            "--range",
            f"1-{max_files}",
            "--filesize-max",
            "25M",
            "--http-timeout",
            "20",
            "--retries",
            "1",
            "--directory",
            str(stage),
            "--whitelist",
            platform,
            url,
        ]
        if runner is not None:
            ret, stderr = runner(cmd, stage)
        else:
            log = stage / "log.txt"
            with log.open("wb") as handle:
                proc = subprocess.Popen(
                    cmd,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    cwd=str(stage),
                    shell=False,
                )
                started = time.monotonic()
                exceeded = False
                while proc.poll() is None:
                    if (time.monotonic() - started) > timeout or folder_size(
                        stage
                    ) > MAX_STAGING_BYTES:
                        exceeded = True
                        proc.terminate()
                        try:
                            proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=3)
                        break
                    time.sleep(0.25)
                ret = 124 if exceeded else (proc.returncode or 0)
            stderr = log.read_text(encoding="utf8", errors="replace")[-1400:]
        # The extractor may have downloaded media before returning a nonzero status.
        for src in sorted(stage.rglob("*")):
            if len(rows) >= max_files or folder_size(project_path) >= MAX_PROJECT_BYTES:
                break
            if not file_safe(src):
                continue
            blob = src.read_bytes()
            if src.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}:
                try:
                    with Image.open(src) as im:
                        im.verify()
                except (UnidentifiedImageError, OSError, ValueError):
                    continue
            sha = hashlib.sha256(blob).hexdigest()
            if sha in known_hashes:
                continue
            name = f"{platform}-{sha[:16]}{src.suffix.lower()}"
            target = dest / name
            shutil.copyfile(src, target)
            known_hashes.add(sha)
            rows.append(
                {
                    "file": target.relative_to(project_path).as_posix(),
                    "platform": platform,
                    "source_profile_url": url,
                    "source_post_url": None,
                    "post_date": None,
                    "post_date_verified": False,
                    "date_filter_requested_after": cutoff_date,
                    "sha256": sha,
                    "bytes": len(blob),
                    "rights_confirmed_for_preview": False,
                    "ownership_verified": False,
                    "downloaded_at": datetime.now(UTC).isoformat(),
                }
            )
    if rows:
        existing.extend(rows)
        manifest_path.write_text(json.dumps(existing, indent=2), encoding="utf8")
    # Date, ownership, source-post URL cannot be assumed from a direct file URL.
    return {
        "status": "collected_needs_review" if rows else "review_needed",
        "files_added": len(rows),
        "platform": platform,
        "cutoff": cutoff_date,
        "project_bytes": folder_size(project_path),
        "extractor_exit_code": ret,
        "extractor_message": stderr[-500:],
        "note": (
            "No platform login used. Confirm source post, published date, ownership "
            "and reuse permission before selecting any photo."
        ),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project", required=True)
    p.add_argument("--platform", required=True, choices=["instagram", "facebook"])
    p.add_argument("--url", required=True)
    p.add_argument("--max-files", type=int, default=40)
    p.add_argument("--days", type=int, default=365)
    args = p.parse_args()
    print(
        json.dumps(
            collect_social(
                args.project,
                args.platform,
                args.url,
                max_files=args.max_files,
                days_limit=args.days,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
