"""Safe post-approval archiving and selective cleanup; never auto-delete.

A production run must provide delivery/retained-assets.json explicitly.
This list is reviewed alongside the approved HTML/GHL code, keeping live file
references intact. All other originals are archived first and pruned only
through a separate --confirm operation after verified ZIP integrity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

ASSET_FOLDERS = (
    "assets/website/",
    "assets/instagram/",
    "assets/facebook/",
    "assets/optimized/",
)
KEEP_BASE = ("research/", "delivery/", "website/")


def read_manifest(project: Path) -> set[str]:
    mf = project / "delivery/retained-assets.json"
    approved = project / "delivery/approved-homepage.html"
    ghl = project / "delivery/ghl-ready.html"
    if not (mf.is_file() and approved.is_file() and ghl.is_file()):
        raise ValueError(
            "Missing retained-assets.json, approved-homepage.html or ghl-ready.html; "
            "cleanup is BLOCKED"
        )
    conf = json.loads(mf.read_text(encoding="utf8"))
    if conf.get("approved") is not True:
        raise ValueError("retained-assets.json must explicitly mark approved=true")
    keep: set[str] = set()
    for item in conf.get("assets", []):
        if not isinstance(item, str) or not any(item.startswith(p) for p in ASSET_FOLDERS):
            raise ValueError(f"Invalid retained path: {item!r}")
        p = (project / item).resolve()
        if not p.is_relative_to(project) or not p.is_file() or p.is_symlink():
            raise ValueError(f"Missing or unsafe retained asset: {item}")
        keep.add(item)
    # Protect any media referenced directly in either deliverable, even if reviewer omitted it.
    text = approved.read_text(encoding="utf8") + "\n" + ghl.read_text(encoding="utf8")
    assets_dir = project / "assets"
    if assets_dir.exists():
        for p in assets_dir.rglob("*"):
            if p.is_file() and not p.is_symlink():
                rel = p.relative_to(project).as_posix()
                if rel in text or rel.replace("assets/", "../assets/") in text:
                    keep.add(rel)
    return keep


def get_plan(project: str | Path) -> tuple[Path, dict[str, Path], list[str], list[str]]:
    project_path = Path(project).resolve()
    if not project_path.is_dir() or project_path.is_symlink():
        raise ValueError("Project directory not found")
    keep = read_manifest(project_path)
    allfiles = {
        p.relative_to(project_path).as_posix(): p
        for p in project_path.rglob("*")
        if p.is_file() and not p.is_symlink()
    }
    archive_set = {key for key in allfiles if key.startswith(KEEP_BASE) or key in keep}
    removable = sorted(key for key in allfiles if key.startswith(ASSET_FOLDERS) and key not in keep)
    return project_path, allfiles, sorted(archive_set), removable


def archive_path(project: Path) -> Path:
    return project.parent / "_archives" / f"{project.name}-approved.zip"


def make_archive(project: str | Path) -> Path:
    project_path, files, keep, _ = get_plan(project)
    out = archive_path(project_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for rel in keep:
                z.write(files[rel], arcname=rel)
        with zipfile.ZipFile(tmp) as z:
            if z.testzip() is not None:
                raise ValueError("ZIP failed CRC verification")
            for rel in keep:
                if (
                    hashlib.sha256(z.read(rel)).digest()
                    != hashlib.sha256(files[rel].read_bytes()).digest()
                ):
                    raise ValueError("Archive SHA256 mismatch")
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    return out


def cleanup(
    project: str | Path,
    mode: str = "plan",
    confirm: bool = False,
) -> dict[str, Any]:
    project_path, files, keep, removable = get_plan(project)
    if (project_path / "delivery").is_dir() and (
        project_path / "delivery" / "release-manifest.json"
    ).is_file():
        from app.approval import verify_release

        verify_release(project_path)

    archive = archive_path(project_path)
    total = sum(files[r].stat().st_size for r in removable)
    if mode == "plan":
        return {
            "mode": mode,
            "removable_count": len(removable),
            "reclaimable_bytes": total,
            "kept_delivery_files": len(keep),
            "sample": removable[:15],
        }
    if mode == "archive":
        return {
            "mode": mode,
            "archive": str(make_archive(project_path)),
            "removable_count": len(removable),
            "reclaimable_bytes": total,
        }
    if mode == "prune":
        if not confirm:
            raise ValueError("Pass --confirm for deletion")
        if not archive.is_file():
            raise ValueError("Verified archive required before cleanup: run --mode archive")
        # Rebuild/check approved archive against current files before every destructive operation.
        make_archive(project_path)
        for rel in removable:
            files[rel].unlink()
        return {
            "mode": mode,
            "deleted_files": len(removable),
            "reclaimed_bytes": total,
            "archive": str(archive),
        }
    raise ValueError("Choose plan, archive, or prune")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--mode", default="plan", choices=["plan", "archive", "prune"])
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()
    print(json.dumps(cleanup(args.project, args.mode, args.confirm), indent=2))


if __name__ == "__main__":
    main()
