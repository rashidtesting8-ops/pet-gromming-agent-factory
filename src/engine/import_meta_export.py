"""Defensive parser and importer for Meta ('Download your information') exports.

Supports Instagram and Facebook export archives (.zip) or extracted folders.
Enforces strict file count, per-file size, total byte, compression-ratio (zip bomb),
and path-traversal guards. Uses real post timestamps from export metadata for
captured_at / post_date, keeps rights_confirmed_for_preview=False until human
confirmation, and logs any unparsed files or records.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import mimetypes
import os
import tempfile
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image, UnidentifiedImageError

from engine.social_collect import IMAGE_EXTENSIONS, strip_image_metadata

ALLOWED_MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | {".mp4", ".webm", ".mov"}
DEFAULT_MAX_FILES = 80
DEFAULT_MAX_ITEM_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 150 * 1024 * 1024
DEFAULT_MAX_ZIP_ENTRIES = 5000
DEFAULT_MAX_COMPRESSION_RATIO = 100.0


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


def _fix_meta_mojibake(text: str) -> str:
    """Repair Meta's common UTF-8-as-Latin-1 mojibake when present, otherwise return as-is."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _parse_timestamp(raw_val: Any) -> str | None:
    """Convert a real Meta export timestamp into UTC ISO-8601 format."""
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
            return None
    return None


def _is_safe_relative_path(raw_rel: str) -> bool:
    """Return True only if raw_rel is a safe relative path with no traversal or drive prefix."""
    cleaned = raw_rel.strip().replace("\\", "/")
    if not cleaned or cleaned.startswith("/") or ":" in cleaned:
        return False
    parts = PurePosixPath(cleaned).parts
    return all(part not in ("", ".", "..") for part in parts)


def _safe_extract_zip(
    zip_path: Path,
    dest_dir: Path,
    *,
    max_item_bytes: int,
    max_total_bytes: int,
    max_zip_entries: int,
    max_compression_ratio: float,
    unparsed: list[dict[str, str]],
) -> None:
    """Safely unpack JSON and media files while guarding against zip bombs/traversal."""
    dest_root = dest_dir.resolve()
    total_unpacked = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        infos = zf.infolist()
        if len(infos) > max_zip_entries:
            unparsed.append(
                {
                    "path": zip_path.name,
                    "reason": f"zip_bomb_too_many_entries:{len(infos)}",
                }
            )
            infos = infos[:max_zip_entries]

        for info in infos:
            entry_name = info.filename
            if info.is_dir():
                continue

            # Reject symlinks inside zip archive
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                unparsed.append({"path": entry_name, "reason": "unsafe_symlink_in_zip"})
                continue

            if not _is_safe_relative_path(entry_name):
                unparsed.append({"path": entry_name, "reason": "unsafe_path_traversal"})
                continue

            target = (dest_root / entry_name.replace("\\", "/")).resolve()
            if not target.is_relative_to(dest_root):
                unparsed.append({"path": entry_name, "reason": "unsafe_path_traversal"})
                continue

            # Check compression ratio for potential zip bomb on non-trivial entries
            if info.file_size > 256 * 1024:
                ratio = info.file_size / max(info.compress_size, 1)
                if ratio > max_compression_ratio and info.file_size > max_item_bytes:
                    unparsed.append(
                        {"path": entry_name, "reason": f"zip_bomb_ratio:{ratio:.1f}"}
                    )
                    continue

            if info.file_size > max_item_bytes:
                unparsed.append(
                    {"path": entry_name, "reason": f"too_large_item:{info.file_size}"}
                )
                continue

            if total_unpacked + info.file_size > max_total_bytes:
                unparsed.append(
                    {"path": entry_name, "reason": "total_bytes_cap_exceeded"}
                )
                continue

            suffix = target.suffix.lower()
            if suffix != ".json" and suffix not in ALLOWED_MEDIA_EXTENSIONS:
                continue

            # Stream read and enforce runtime byte limits even if ZipInfo header lied
            buf = bytearray()
            exceeded_item = False
            exceeded_total = False
            with zf.open(info, "r") as stream:
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        break
                    if len(buf) + len(chunk) > max_item_bytes:
                        exceeded_item = True
                        break
                    if total_unpacked + len(buf) + len(chunk) > max_total_bytes:
                        exceeded_total = True
                        break
                    buf.extend(chunk)

            if exceeded_item:
                unparsed.append({"path": entry_name, "reason": "zip_bomb_stream_too_large"})
                continue
            if exceeded_total:
                unparsed.append({"path": entry_name, "reason": "total_bytes_cap_exceeded"})
                break

            total_unpacked += len(buf)
            _atomic_write_bytes(target, bytes(buf))


def _extract_media_entries_from_node(
    node: Any,
    *,
    source_json: str,
    inherited_ts: Any = None,
    inherited_caption: str | None = None,
    entries_out: list[dict[str, Any]],
    unparsed: list[dict[str, str]],
) -> None:
    """Recursively traverse Meta export JSON structures to find media items."""
    if isinstance(node, list):
        for item in node:
            _extract_media_entries_from_node(
                item,
                source_json=source_json,
                inherited_ts=inherited_ts,
                inherited_caption=inherited_caption,
                entries_out=entries_out,
                unparsed=unparsed,
            )
        return

    if not isinstance(node, dict):
        return

    local_ts = (
        node.get("creation_timestamp")
        or node.get("timestamp")
        or node.get("taken_at")
        or inherited_ts
    )

    local_caption = inherited_caption
    for cap_key in ("title", "description", "caption", "post"):
        val = node.get(cap_key)
        if isinstance(val, str) and val.strip():
            local_caption = _fix_meta_mojibake(val.strip())
            break
    if local_caption is None and isinstance(node.get("data"), list):
        for d_item in node["data"]:
            if isinstance(d_item, dict) and isinstance(d_item.get("post"), str):
                text = d_item["post"].strip()
                if text:
                    local_caption = _fix_meta_mojibake(text)
                    break

    uri = node.get("uri")
    if isinstance(uri, str) and uri.strip():
        parsed_ts = _parse_timestamp(local_ts)
        if parsed_ts is None:
            unparsed.append(
                {
                    "path": f"{source_json}:{uri}",
                    "reason": "missing_or_invalid_timestamp",
                }
            )
        else:
            entries_out.append(
                {
                    "uri": uri.strip(),
                    "timestamp_iso": parsed_ts,
                    "caption": local_caption,
                    "source_json": source_json,
                }
            )

    # Traverse known or unknown container fields holding lists/dicts of posts/attachments/media
    for key, value in node.items():
        if key in ("uri", "media_metadata", "exif_data", "camera_metadata"):
            continue
        if isinstance(value, list | dict):
            _extract_media_entries_from_node(
                value,
                source_json=source_json,
                inherited_ts=local_ts,
                inherited_caption=local_caption,
                entries_out=entries_out,
                unparsed=unparsed,
            )


def _detect_platform(export_root: Path, requested: str) -> str:
    if requested in ("instagram", "facebook"):
        return requested
    for p in export_root.rglob("*.json"):
        rel = p.relative_to(export_root).as_posix().lower()
        if "facebook" in rel or "your_posts" in rel:
            return "facebook"
        if "instagram" in rel or "igtv" in rel or "reels" in rel:
            return "instagram"
    return "instagram"


def import_meta_export(
    project_folder: str | Path,
    export_path: str | Path,
    *,
    platform: str = "auto",
    max_files: int = DEFAULT_MAX_FILES,
    max_item_bytes: int = DEFAULT_MAX_ITEM_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_zip_entries: int = DEFAULT_MAX_ZIP_ENTRIES,
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
) -> dict[str, Any]:
    """Parse an Instagram or Facebook export (zip or folder) into the project asset manifests."""
    if platform not in ("instagram", "facebook", "auto"):
        raise ValueError("platform must be 'instagram', 'facebook', or 'auto'")
    if not 1 <= max_files <= 500:
        raise ValueError("max_files must be 1..500")
    if max_item_bytes <= 0 or max_total_bytes <= 0:
        raise ValueError("max_item_bytes and max_total_bytes must be positive")

    project_root = Path(project_folder).resolve()
    if not project_root.is_dir():
        raise ValueError("Project folder does not exist")

    research_dir = project_root / "research"
    research_dir.mkdir(parents=True, exist_ok=True)

    source = Path(export_path).resolve()
    if not source.exists():
        raise ValueError(f"Export path does not exist: {export_path}")

    unparsed: list[dict[str, str]] = []
    warnings: list[str] = []

    with tempfile.TemporaryDirectory(prefix="pet-meta-export-") as td:
        if source.is_file() and source.suffix.lower() == ".zip":
            export_root = Path(td).resolve()
            try:
                _safe_extract_zip(
                    source,
                    export_root,
                    max_item_bytes=max_item_bytes,
                    max_total_bytes=max_total_bytes,
                    max_zip_entries=max_zip_entries,
                    max_compression_ratio=max_compression_ratio,
                    unparsed=unparsed,
                )
            except (zipfile.BadZipFile, OSError) as exc:
                unparsed.append({"path": source.name, "reason": f"invalid_zip:{exc}"})
                return {
                    "status": "review_needed",
                    "reason": "invalid_zip_archive",
                    "files_added": 0,
                    "bytes_added": 0,
                    "unparsed": unparsed,
                    "warnings": warnings,
                }
        elif source.is_dir():
            export_root = source
        else:
            raise ValueError("export_path must be a directory or a .zip archive")

        resolved_platform = _detect_platform(export_root, platform)
        dest_dir = project_root / "assets" / resolved_platform
        opt_dir = project_root / "assets" / "optimized"
        dest_dir.mkdir(parents=True, exist_ok=True)
        opt_dir.mkdir(parents=True, exist_ok=True)

        media_entries: list[dict[str, Any]] = []
        for json_file in sorted(export_root.rglob("*.json")):
            if json_file.is_symlink():
                unparsed.append({"path": str(json_file.name), "reason": "unsafe_symlink"})
                continue
            rel_json = json_file.relative_to(export_root).as_posix()
            try:
                if json_file.stat().st_size > max_item_bytes:
                    unparsed.append({"path": rel_json, "reason": "json_too_large"})
                    continue
                raw_text = json_file.read_text(encoding="utf-8", errors="replace")
                parsed = json.loads(raw_text)
            except (OSError, json.JSONDecodeError) as exc:
                unparsed.append({"path": rel_json, "reason": f"invalid_json:{exc}"})
                continue

            _extract_media_entries_from_node(
                parsed,
                source_json=rel_json,
                entries_out=media_entries,
                unparsed=unparsed,
            )

        asset_manifest_path = research_dir / "asset-manifest.json"
        social_manifest_path = research_dir / "social-media-manifest.json"
        log_path = research_dir / "meta-export-import-log.json"

        asset_manifest: list[dict[str, Any]] = (
            json.loads(asset_manifest_path.read_text(encoding="utf-8"))
            if asset_manifest_path.exists()
            else []
        )
        social_manifest: list[dict[str, Any]] = (
            json.loads(social_manifest_path.read_text(encoding="utf-8"))
            if social_manifest_path.exists()
            else []
        )

        known_hashes = {
            str(r["sha256"])
            for r in (*asset_manifest, *social_manifest)
            if isinstance(r, dict) and "sha256" in r
        }

        added_assets: list[dict[str, Any]] = []
        added_social: list[dict[str, Any]] = []
        bytes_added = 0

        for item in media_entries:
            if len(added_assets) >= max_files:
                warnings.append(f"Reached max_files cap ({max_files})")
                break

            uri = str(item["uri"])
            if not _is_safe_relative_path(uri):
                unparsed.append({"path": uri, "reason": "unsafe_path_traversal_in_uri"})
                continue

            media_path = (export_root / uri.replace("\\", "/")).resolve()
            if not media_path.is_relative_to(export_root):
                unparsed.append({"path": uri, "reason": "unsafe_path_traversal_in_uri"})
                continue

            if not media_path.is_file() or media_path.is_symlink():
                unparsed.append({"path": uri, "reason": "missing_or_unsafe_media_file"})
                continue

            suffix = media_path.suffix.lower()
            if suffix not in ALLOWED_MEDIA_EXTENSIONS:
                unparsed.append({"path": uri, "reason": f"unsupported_extension:{suffix}"})
                continue

            size = media_path.stat().st_size
            if size <= 0 or size > max_item_bytes:
                unparsed.append({"path": uri, "reason": f"too_large_or_empty:{size}"})
                continue
            if bytes_added + size > max_total_bytes:
                unparsed.append({"path": uri, "reason": "total_bytes_cap_exceeded"})
                break

            blob = media_path.read_bytes()
            is_image = suffix in IMAGE_EXTENSIONS
            width: int | None = None
            height: int | None = None
            if is_image:
                try:
                    with Image.open(io.BytesIO(blob)) as im:
                        width, height = im.width, im.height
                        im.verify()
                except (UnidentifiedImageError, OSError, ValueError):
                    unparsed.append({"path": uri, "reason": "corrupt_image"})
                    continue

            sha = hashlib.sha256(blob).hexdigest()
            if sha in known_hashes:
                continue

            fname = f"{resolved_platform}-export-{sha[:16]}{suffix}"
            target_file = dest_dir / fname
            _atomic_write_bytes(target_file, blob)

            optimized_rel: str | None = None
            if is_image:
                opt_target = opt_dir / fname
                try:
                    strip_image_metadata(media_path, opt_target)
                    optimized_rel = opt_target.relative_to(project_root).as_posix()
                except (UnidentifiedImageError, OSError, ValueError):
                    target_file.unlink(missing_ok=True)
                    unparsed.append({"path": uri, "reason": "corrupt_image_on_optimize"})
                    continue

            rel_local = target_file.relative_to(project_root).as_posix()
            mime = mimetypes.guess_type(fname)[0] or "application/octet-stream"
            post_ts = str(item["timestamp_iso"])
            source_url = f"meta_export://{resolved_platform}/{uri.lstrip('/')}"
            caption = item.get("caption")

            asset_row: dict[str, Any] = {
                "asset_id": f"{resolved_platform}-export-{sha[:12]}",
                "status": "imported",
                "platform": resolved_platform,
                "source_url": source_url,
                "page_url": source_url,
                "file": rel_local,
                "local_path": rel_local,
                "optimized_file": optimized_rel,
                "sha256": sha,
                "bytes": len(blob),
                "width": width,
                "height": height,
                "dimensions": [width, height] if width and height else None,
                "mime": mime,
                "captured_at": post_ts,
                "post_date": post_ts,
                "post_date_verified": True,
                "rights_confirmed_for_preview": False,
                "category": "social_export",
                "notes": caption,
            }
            social_row: dict[str, Any] = {
                "file": rel_local,
                "optimized_file": optimized_rel,
                "platform": resolved_platform,
                "source_url": source_url,
                "original_post_url": None,
                "sha256": sha,
                "bytes": len(blob),
                "captured_at": post_ts,
                "post_date": post_ts,
                "post_date_verified": True,
                "rights_confirmed_for_preview": False,
                "ownership_verified": False,
                "notes": caption,
            }

            known_hashes.add(sha)
            bytes_added += len(blob)
            added_assets.append(asset_row)
            added_social.append(social_row)

        if added_assets:
            asset_manifest.extend(added_assets)
            social_manifest.extend(added_social)
            _atomic_write_text(asset_manifest_path, json.dumps(asset_manifest, indent=2))
            _atomic_write_text(social_manifest_path, json.dumps(social_manifest, indent=2))

        report: dict[str, Any] = {
            "status": "imported_needs_review" if added_assets else "review_needed",
            "platform": resolved_platform,
            "files_added": len(added_assets),
            "bytes_added": bytes_added,
            "unparsed": unparsed,
            "warnings": warnings,
        }
        _atomic_write_text(log_path, json.dumps(report, indent=2))
        return report


def run_cli(argv: Sequence[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(
        description="Import an Instagram or Facebook 'Download your information' export."
    )
    parser.add_argument("--project", required=True, help="Target project directory")
    parser.add_argument("--export", required=True, help="Path to export .zip or directory")
    parser.add_argument(
        "--platform",
        choices=["instagram", "facebook", "auto"],
        default="auto",
    )
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    args = parser.parse_args(list(argv) if argv is not None else None)
    return import_meta_export(
        project_folder=args.project,
        export_path=args.export,
        platform=args.platform,
        max_files=args.max_files,
    )


def main() -> None:
    print(json.dumps(run_cli(), indent=2))


if __name__ == "__main__":
    main()
