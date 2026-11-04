"""Backward-compatible shim for engine.contact_sheet."""

from __future__ import annotations

from engine.contact_sheet import main, make_sheet

__all__ = ["main", "make_sheet"]

if __name__ == "__main__":
    main()

