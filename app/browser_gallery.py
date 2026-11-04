"""Backward-compatible shim for engine.browser_gallery."""

from __future__ import annotations

from engine.browser_gallery import main, render_gallery

__all__ = ["main", "render_gallery"]

if __name__ == "__main__":
    main()

