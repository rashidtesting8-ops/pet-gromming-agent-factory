"""Backward-compatible shim for engine.collector."""

from __future__ import annotations

from engine.collector import (
    AGENT,
    BAD_PAGE_HINTS,
    DEFAULT_MAX_MEDIA,
    MAX_SITE_BYTES,
    MEDIA_EXTENSIONS,
    MEDIA_TYPES,
    PAGE_HINTS,
    USER_AGENT,
    candidate_url,
    choose_srcset,
    collect,
    collect_page_text,
    download_one,
    grab_media,
    main,
    media_type,
    normalize_page_url,
    now,
    response_get,
    robots_allowed,
    safe_url,
    same_site,
    slugify,
)

__all__ = [
    "AGENT",
    "BAD_PAGE_HINTS",
    "DEFAULT_MAX_MEDIA",
    "MAX_SITE_BYTES",
    "MEDIA_EXTENSIONS",
    "MEDIA_TYPES",
    "PAGE_HINTS",
    "USER_AGENT",
    "candidate_url",
    "choose_srcset",
    "collect",
    "collect_page_text",
    "download_one",
    "grab_media",
    "main",
    "media_type",
    "normalize_page_url",
    "now",
    "response_get",
    "robots_allowed",
    "safe_url",
    "same_site",
    "slugify",
]

if __name__ == "__main__":
    main()

