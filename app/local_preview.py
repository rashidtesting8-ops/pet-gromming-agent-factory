"""Backward-compatible shim for engine.local_preview."""

from __future__ import annotations

from engine.local_preview import WIDTHS, check_local_html, main

__all__ = ["WIDTHS", "check_local_html", "main"]

if __name__ == "__main__":
    main()

