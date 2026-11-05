"""Backward-compatible shim for engine.exporter."""

from __future__ import annotations

from engine.exporter import (
    check_used_asset_rights,
    export_release,
    extract_used_assets,
    main,
    run_cli,
)

__all__ = [
    "check_used_asset_rights",
    "export_release",
    "extract_used_assets",
    "main",
    "run_cli",
]

if __name__ == "__main__":
    main()

