"""Backward-compatible shim for engine.import_social_media."""

from __future__ import annotations

from engine.import_social_media import ALLOWED, import_media, main

__all__ = ["ALLOWED", "import_media", "main"]

if __name__ == "__main__":
    main()

