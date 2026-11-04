"""Backward-compatible shim for engine.social_collect."""

from __future__ import annotations

from engine.social_collect import (
    ALLOWED,
    MAX_ITEM_BYTES,
    MAX_PROJECT_BYTES,
    MAX_STAGING_BYTES,
    SOCIAL_HOSTS,
    check_social_url,
    collect_social,
    cutoff_year,
    file_safe,
    folder_size,
    main,
)

__all__ = [
    "ALLOWED",
    "MAX_ITEM_BYTES",
    "MAX_PROJECT_BYTES",
    "MAX_STAGING_BYTES",
    "SOCIAL_HOSTS",
    "check_social_url",
    "collect_social",
    "cutoff_year",
    "file_safe",
    "folder_size",
    "main",
]

if __name__ == "__main__":
    main()

