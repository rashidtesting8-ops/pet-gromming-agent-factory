"""Backward-compatible shim for engine.cleanup."""

from __future__ import annotations

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

__all__ = [
    "ASSET_FOLDERS",
    "KEEP_BASE",
    "archive_path",
    "cleanup",
    "get_plan",
    "main",
    "make_archive",
    "read_manifest",
]

if __name__ == "__main__":
    main()

