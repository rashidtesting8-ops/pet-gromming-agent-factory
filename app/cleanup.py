"""Safe post-approval archiving and selective cleanup; never auto-delete.

Enforces the EditVista Retention Invariant:
- NEVER delete files listed in `delivery/retained-assets.json` or any file under `delivery/`.
- Pruning is strictly BLOCKED if `projects/_archives/<business-id>-approved.zip` does not exist.
- Supports both `cleanup(project, mode=..., confirm=...)` and
  `safe_prune_project(project, dry_run=True | False)`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.cleanup import (
    ASSET_FOLDERS,
    KEEP_BASE,
    archive_path,
    cleanup,
    get_plan,
    main,
    make_archive,
    read_manifest,
)

TEMP_WORKING_FOLDERS = (
    "tmp/",
    "staging/",
    ".tmp/",
)


def safe_prune_project(
    project: str | Path,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Approval-gated cleanup for unreferenced staging files and temporary scraper folders.

    - Strictly BLOCKED if `projects/_archives/<business-id>-approved.zip` does not exist.
    - Never touches files in `delivery/` or `delivery/retained-assets.json`.
    - In `dry_run=True` mode, returns the manifest of eligible files without deleting.
    - In `dry_run=False` (execute) mode, deletes only verified unreferenced staging files
      in `assets/website/`, `assets/instagram/`, `assets/facebook/`, and temporary folders.
    """
    project_path = Path(project).resolve()
    if (project_path / "delivery").is_dir() and (
        project_path / "delivery" / "release-manifest.json"
    ).is_file():
        from app.approval import verify_release

        verify_release(project_path)

    archive_zip = archive_path(project_path)
    if not archive_zip.is_file():
        raise ValueError(
            f"Pruning is strictly BLOCKED: verified archive {archive_zip} does not exist"
        )

    _, allfiles, keep, removable_assets = get_plan(project_path)
    keep_set = set(keep)

    temp_files: list[str] = []
    for rel, file_path in sorted(allfiles.items()):
        if rel.startswith("delivery/") or rel in keep_set:
            continue
        if rel.startswith(TEMP_WORKING_FOLDERS) and file_path.is_file():
            temp_files.append(rel)

    eligible = sorted(
        rel
        for rel in dict.fromkeys([*removable_assets, *temp_files])
        if not rel.startswith("delivery/") and rel not in keep_set
    )
    reclaimable_bytes = sum(allfiles[r].stat().st_size for r in eligible if r in allfiles)

    if dry_run:
        return {
            "project_id": project_path.name,
            "dry_run": True,
            "archive_path": str(archive_zip),
            "eligible_count": len(eligible),
            "eligible_for_deletion": eligible,
            "reclaimable_bytes": reclaimable_bytes,
        }

    # Verify archive integrity before deleting any unreferenced file
    make_archive(project_path)

    deleted: list[str] = []
    for rel in eligible:
        if rel.startswith("delivery/") or rel in keep_set:
            continue
        target = allfiles.get(rel)
        if target and target.is_file() and not target.is_symlink():
            target.unlink()
            deleted.append(rel)

    return {
        "project_id": project_path.name,
        "dry_run": False,
        "archive_path": str(archive_zip),
        "deleted_count": len(deleted),
        "deleted_files": deleted,
        "reclaimed_bytes": reclaimable_bytes,
    }


__all__ = [
    "ASSET_FOLDERS",
    "KEEP_BASE",
    "TEMP_WORKING_FOLDERS",
    "archive_path",
    "cleanup",
    "get_plan",
    "main",
    "make_archive",
    "read_manifest",
    "safe_prune_project",
]

if __name__ == "__main__":
    main()
