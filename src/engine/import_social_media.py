"""Register and copy legitimately obtained Instagram/Facebook media into a project folder.

Does not download from or bypass Meta social platforms. Every file retains source
post URL and review flags for the later visual curator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.contracts import atomic_write_json

ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".mp4", ".webm", ".mov"}


def import_media(
    project_folder: str | Path,
    platform: str,
    source_url: str,
    files: Sequence[str | Path],
    rights_confirmed: bool = False,
) -> list[dict[str, Any]]:
    if platform not in ("instagram", "facebook"):
        raise ValueError("platform must be instagram or facebook")
    root = Path(project_folder)
    if not root.exists():
        raise ValueError("Project folder does not exist")
    target = root / "assets" / platform
    target.mkdir(parents=True, exist_ok=True)
    provenance_path = root / "research" / "social-media-manifest.json"
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = (
        json.loads(provenance_path.read_text(encoding="utf-8"))
        if provenance_path.exists()
        else []
    )
    imported: list[dict[str, Any]] = []
    for f in files:
        src = Path(f)
        if not src.is_file() or src.suffix.lower() not in ALLOWED:
            raise ValueError(f"Not a supported media file: {f}")
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
        name = f"{src.stem[:40]}-{sha[:12]}{src.suffix.lower()}"
        dst = target / name
        if not dst.exists():
            shutil.copy2(src, dst)
        now_iso = datetime.now(UTC).isoformat()
        row: dict[str, Any] = {
            "file": dst.relative_to(root).as_posix(),
            "platform": platform,
            "source_url": source_url,
            "source_post_url": source_url,
            "sha256": sha,
            "rights_confirmed_for_preview": bool(rights_confirmed),
            "ownership_verified": False,
            "captured_at": now_iso,
            "imported_at": now_iso,
        }
        if not any(r.get("sha256") == sha for r in rows):
            rows.append(row)
        imported.append(row)
    atomic_write_json(provenance_path, rows, ensure_ascii=True)
    return imported


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--platform", choices=["instagram", "facebook"], required=True)
    ap.add_argument("--source-url", required=True, help="Original public post URL")
    ap.add_argument(
        "--rights-confirmed",
        action="store_true",
        help="You confirm permission to use assets in this preview",
    )
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()
    print(
        json.dumps(
            import_media(
                args.project,
                args.platform,
                args.source_url,
                args.files,
                args.rights_confirmed,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

