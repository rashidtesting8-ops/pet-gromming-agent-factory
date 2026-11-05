"""Backward-compatible shim for engine.import_meta_export."""

from __future__ import annotations

from engine.import_meta_export import (
    ALLOWED_MEDIA_EXTENSIONS,
    DEFAULT_MAX_COMPRESSION_RATIO,
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_ITEM_BYTES,
    DEFAULT_MAX_TOTAL_BYTES,
    DEFAULT_MAX_ZIP_ENTRIES,
    import_meta_export,
    main,
    run_cli,
)

__all__ = [
    "ALLOWED_MEDIA_EXTENSIONS",
    "DEFAULT_MAX_COMPRESSION_RATIO",
    "DEFAULT_MAX_FILES",
    "DEFAULT_MAX_ITEM_BYTES",
    "DEFAULT_MAX_TOTAL_BYTES",
    "DEFAULT_MAX_ZIP_ENTRIES",
    "import_meta_export",
    "main",
    "run_cli",
]

if __name__ == "__main__":
    main()

