"""Backward-compatible shim for engine.local_preview."""

from __future__ import annotations

from engine.local_preview import (
    WIDTHS,
    check_local_html,
    check_mobile_menu_static,
    check_reduced_motion_static,
    is_bad_link_href,
    main,
)

__all__ = [
    "WIDTHS",
    "check_local_html",
    "check_mobile_menu_static",
    "check_reduced_motion_static",
    "is_bad_link_href",
    "main",
]

if __name__ == "__main__":
    main()
