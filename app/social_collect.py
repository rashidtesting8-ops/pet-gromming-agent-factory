"""Backward-compatible shim for engine.social_collect."""

from __future__ import annotations

from engine.social_collect import (
    ALLOWED,
    MAX_ITEM_BYTES,
    MAX_PROJECT_BYTES,
    MAX_STAGING_BYTES,
    SOCIAL_HOSTS,
    check_social_url,
    classify_social_failure,
    collect_social,
    cutoff_year,
    derive_post_metadata,
    file_safe,
    folder_size,
    main,
    parse_dump_json_metadata,
    run_cli,
    scrub_sensitive_text,
    strip_image_metadata,
)

__all__ = [
    "ALLOWED",
    "MAX_ITEM_BYTES",
    "MAX_PROJECT_BYTES",
    "MAX_STAGING_BYTES",
    "SOCIAL_HOSTS",
    "check_social_url",
    "classify_social_failure",
    "collect_social",
    "cutoff_year",
    "derive_post_metadata",
    "file_safe",
    "folder_size",
    "main",
    "parse_dump_json_metadata",
    "run_cli",
    "scrub_sensitive_text",
    "strip_image_metadata",
]

if __name__ == "__main__":
    main()
