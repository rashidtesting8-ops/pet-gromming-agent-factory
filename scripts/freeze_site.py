"""Freeze live or local site pages and snapshots into tests/golden/<slug>/ fixture.

Reuses the engine's safe collector (src/engine/collector.py) to crawl and save:
- research/pages.json
- research/snapshots/<sha256>.html
along with a hand-written expected.json specifying facts, normalized values, and statuses.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from engine.collector import collect


def freeze_site(
    url: str,
    slug: str,
    *,
    output_dir: str | Path = "tests/golden",
    expected_facts: list[dict[str, Any]] | None = None,
    max_pages: int = 5,
    max_media: int = 20,
    allow_private: bool = False,
) -> Path:
    """Freeze crawled pages and HTML snapshots into golden fixture directory."""
    clean_slug = slug.strip().lower().replace("_", "-")
    target_root = Path(output_dir).resolve() / clean_slug
    target_research = target_root / "research"
    target_snapshots = target_research / "snapshots"
    target_snapshots.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        crawl_summary = collect(
            url,
            tmp_path,
            max_pages=max_pages,
            max_media=max_media,
            allow_private=allow_private,
        )

        crawled_root = Path(str(crawl_summary.get("project_folder", tmp_path)))
        crawled_research = crawled_root / "research"
        src_pages = crawled_research / "pages.json"
        if src_pages.is_file():
            shutil.copy2(src_pages, target_research / "pages.json")

        src_snaps = crawled_research / "snapshots"
        if src_snaps.is_dir():
            for snap in src_snaps.glob("*.html"):
                shutil.copy2(snap, target_snapshots / snap.name)

    # Write expected.json template if not already present
    expected_file = target_root / "expected.json"
    if expected_facts is not None:
        expected_file.write_text(json.dumps(expected_facts, indent=2), encoding="utf-8")
    elif not expected_file.is_file():
        default_template: list[dict[str, Any]] = [
            {
                "category": "business_name",
                "normalized_value": clean_slug.replace("-", " ").title(),
                "claim_key": "business_name",
                "expected_status": "verified",
            }
        ]
        expected_file.write_text(json.dumps(default_template, indent=2), encoding="utf-8")

    return target_root


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.freeze_site",
        description="Freeze website pages and snapshots into tests/golden/<slug>/.",
    )
    parser.add_argument("--url", required=True, help="Target URL to crawl safely")
    parser.add_argument("--slug", required=True, help="Directory slug under tests/golden/")
    parser.add_argument("--output-dir", default="tests/golden", help="Output directory")
    parser.add_argument(
        "--expected-file",
        default=None,
        help="Optional path to existing expected.json to install",
    )
    parser.add_argument(
        "--allow-private",
        action="store_true",
        help="Allow local / private IPs (for testing)",
    )
    args = parser.parse_args(argv)

    expected_facts = None
    if args.expected_file:
        p = Path(args.expected_file).resolve()
        if p.is_file():
            expected_facts = json.loads(p.read_text(encoding="utf-8"))

    dest = freeze_site(
        url=args.url,
        slug=args.slug,
        output_dir=args.output_dir,
        expected_facts=expected_facts,
        allow_private=bool(args.allow_private),
    )
    print(f"Successfully froze site into: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
