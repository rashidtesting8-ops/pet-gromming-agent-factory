"""Master End-to-End Orchestrator Pipeline for EditVista Pet Grooming Website Builder Engine.

CLI Entrypoint:
  `python -m app.pipeline --url <TARGET_URL> --name <BUSINESS_NAME> [--business-id <ID>]`

Executes the 9-step pipeline with atomic SQLite job state transitions via `immediate_transaction`:
1. Initialize project record in SQLite (`app/db.py`).
2. Collect website pages & media candidates (`app/collector.py`, `app/social_collect.py`).
3. Extract and verify business facts (`app/fact_extractor.py`).
4. Curate images, rank hero shots, and calculate focal points (`app/curator.py`).
5. Synthesize brand colors and creative brief (`app/art_director.py`).
6. Generate semantic HTML5/CSS/JS website code (`app/generator.py`).
7. Execute 5-viewport Playwright QA across 1440, 1024, 768, 390, 360px (`app/qa_engine.py`).
8. If QA passes with zero critical errors, compile `delivery/approved-homepage.html` and
   scoped `delivery/ghl-ready.html` (`app/ghl_exporter.py`).
9. Record completed job states and provenance records atomically in SQLite.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.art_director import generate_art_direction
from app.collector import collect, slugify
from app.curator import curate_project_images
from app.db import (
    AssetProvenanceRecord,
    BusinessFactRecord,
    JobRunRecord,
    ProjectRecord,
    connect_db,
    init_db,
    upsert_asset_provenance,
    upsert_business_fact,
    upsert_job_run,
    upsert_project,
)
from app.fact_extractor import extract_business_facts
from app.generator import generate_website
from app.ghl_exporter import export_ghl_snippet
from app.qa_engine import QADefectReport, run_qa_engine

QARunnerFn = Callable[..., QADefectReport]


def _atomic_write_text(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


class PipelineRunResult(BaseModel):
    """Structured result returned by `run_pipeline`."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    business_name: str
    primary_url: str
    project_folder: Path
    status: str
    qa_passed: bool
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _record_job_transition(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    module_name: str,
    status: str,
    error_message: str | None = None,
) -> JobRunRecord:
    run_id = f"{project_id}:{module_name}"
    record = JobRunRecord(
        run_id=run_id,
        project_id=project_id,
        module_name=module_name,
        status=status,
        idempotency_key=f"idemp:{run_id}",
        error_message=error_message,
    )
    return upsert_job_run(conn, record)


def _stage_downloaded_assets_for_curator(
    conn: sqlite3.Connection,
    project_root: Path,
    project_id: str,
) -> list[AssetProvenanceRecord]:
    """Copy downloaded website media into `assets/optimized/` and record SQLite provenance."""
    manifest_path = project_root / "research" / "asset-manifest.json"
    optimized_dir = project_root / "assets" / "optimized"
    optimized_dir.mkdir(parents=True, exist_ok=True)
    provenance_records: list[AssetProvenanceRecord] = []

    if not manifest_path.is_file():
        return provenance_records

    items: list[dict[str, Any]] = json.loads(manifest_path.read_text(encoding="utf-8"))
    for idx, item in enumerate(items, start=1):
        if item.get("status") != "downloaded":
            continue
        rel_file = str(item.get("file", ""))
        sha256 = str(item.get("sha256", ""))
        src_url = str(item.get("url", ""))
        if not rel_file or not sha256:
            continue

        src_path = project_root / rel_file
        if not src_path.is_file():
            continue

        dest_path = optimized_dir / src_path.name
        if not dest_path.is_file():
            shutil.copy2(src_path, dest_path)

        rec = AssetProvenanceRecord(
            asset_id=f"asset-{idx}-{sha256[:10]}",
            project_id=project_id,
            sha256_hash=sha256,
            source_url=src_url or "https://local.invalid/asset",
            local_path=rel_file,
            rights_confirmed_for_preview=bool(item.get("rights_confirmed_for_preview", False)),
        )
        upsert_asset_provenance(conn, rec)
        provenance_records.append(rec)

    return provenance_records


def _build_standalone_approved_homepage(project_root: Path) -> Path:
    """Compile standalone `delivery/approved-homepage.html` with inlined CSS/JS from `website/`."""
    website_dir = project_root / "website"
    index_path = website_dir / "index.html"
    css_path = website_dir / "css" / "styles.css"
    js_path = website_dir / "js" / "main.js"

    html_doc = index_path.read_text(encoding="utf-8")
    if css_path.is_file():
        css_text = css_path.read_text(encoding="utf-8")
        html_doc = html_doc.replace(
            '<link rel="stylesheet" href="css/styles.css">',
            f"<style>\n{css_text}\n</style>",
        )
    if js_path.is_file():
        js_text = js_path.read_text(encoding="utf-8")
        html_doc = html_doc.replace(
            '<script src="js/main.js"></script>',
            f"<script>\n{js_text}\n</script>",
        )

    out_path = project_root / "delivery" / "approved-homepage.html"
    _atomic_write_text(out_path, html_doc)
    return out_path


def run_pipeline(
    *,
    url: str,
    business_name: str,
    business_id: str | None = None,
    projects_dir: str | Path = "./projects",
    db_path: str | Path | None = None,
    allow_private: bool = False,
    qa_runner: QARunnerFn | None = None,
) -> PipelineRunResult:
    """Execute the end-to-end 9-step EditVista website generation pipeline."""
    projects_root = Path(projects_dir).resolve()
    projects_root.mkdir(parents=True, exist_ok=True)

    project_id = slugify(business_id or business_name)
    project_root = projects_root / project_id
    resolved_db_path = Path(db_path).resolve() if db_path else (projects_root / "editvista.sqlite3")

    warnings: list[str] = []
    errors: list[str] = []
    active_qa_runner = qa_runner or run_qa_engine

    conn = connect_db(resolved_db_path)
    try:
        # Step 1: Initialize database schema and project record
        init_db(conn)
        upsert_project(
            conn,
            ProjectRecord(
                project_id=project_id,
                business_name=business_name,
                primary_url=url,
                status="running",
            ),
        )

        # Step 2: Collect website pages & media candidates
        _record_job_transition(
            conn, project_id=project_id, module_name="collector", status="running"
        )
        try:
            staging_collect_dir = projects_root / f".collect_staging_{project_id}"
            if staging_collect_dir.exists():
                shutil.rmtree(staging_collect_dir)
            collect_summary = collect(
                url,
                staging_collect_dir,
                max_pages=10,
                max_media=40,
                allow_private=allow_private,
            )
            crawled_folder = Path(str(collect_summary["project_folder"]))
            if project_root.exists():
                shutil.rmtree(project_root)
            shutil.move(str(crawled_folder), str(project_root))
            shutil.rmtree(staging_collect_dir, ignore_errors=True)
            _record_job_transition(
                conn, project_id=project_id, module_name="collector", status="completed"
            )
        except Exception as exc:
            # Non-critical collector fallback: log warning and bootstrap minimal pages.json
            warnings.append(f"collector_warning: {exc}")
            for sub in (
                "assets/website",
                "assets/optimized",
                "research/snapshots",
                "design",
                "website",
                "qa",
                "delivery",
            ):
                (project_root / sub).mkdir(parents=True, exist_ok=True)
            fallback_pages = [
                {
                    "url": url,
                    "sha256": "0" * 64,
                    "title": business_name,
                    "description": business_name,
                    "text": business_name,
                }
            ]
            _atomic_write_text(
                project_root / "research" / "pages.json",
                json.dumps(fallback_pages, indent=2),
            )
            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="collector",
                status="completed",
                error_message=f"warning: {exc}",
            )

        provenance_records = _stage_downloaded_assets_for_curator(conn, project_root, project_id)

        # Step 3: Extract and verify business facts
        _record_job_transition(
            conn, project_id=project_id, module_name="fact_extractor", status="running"
        )
        facts_report = extract_business_facts(project_root)
        for fact in facts_report.facts:
            upsert_business_fact(
                conn,
                BusinessFactRecord(
                    fact_id=fact.fact_id,
                    project_id=project_id,
                    category=fact.category,
                    claim_key=fact.claim_key,
                    claim_value=fact.claim_value,
                    source_url=fact.source_url,
                    source_text_snippet=fact.source_text_snippet,
                    is_verified=fact.is_verified,
                ),
            )
        _record_job_transition(
            conn, project_id=project_id, module_name="fact_extractor", status="completed"
        )

        # Step 4: Curate images, rank hero shots, and calculate focal points
        _record_job_transition(
            conn, project_id=project_id, module_name="curator", status="running"
        )
        curate_res = curate_project_images(project_root)
        warnings.extend(curate_res.warnings)
        _record_job_transition(
            conn, project_id=project_id, module_name="curator", status="completed"
        )

        # Step 5: Synthesize brand colors and creative brief
        _record_job_transition(
            conn, project_id=project_id, module_name="art_director", status="running"
        )
        generate_art_direction(project_root, provenance_records=provenance_records)
        _record_job_transition(
            conn, project_id=project_id, module_name="art_director", status="completed"
        )

        # Step 6: Generate semantic website code in website/
        _record_job_transition(
            conn, project_id=project_id, module_name="generator", status="running"
        )
        generate_website(project_root)
        _record_job_transition(
            conn, project_id=project_id, module_name="generator", status="completed"
        )

        # Step 7: Execute 5-viewport Playwright QA across 1440, 1024, 768, 390, 360px
        _record_job_transition(
            conn, project_id=project_id, module_name="qa_engine", status="running"
        )
        qa_report = active_qa_runner(project_root)
        if not qa_report.passed:
            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="qa_engine",
                status="failed",
                error_message="QA report detected critical viewport defects",
            )
            upsert_project(
                conn,
                ProjectRecord(
                    project_id=project_id,
                    business_name=business_name,
                    primary_url=url,
                    status="needs_review",
                ),
            )
            return PipelineRunResult(
                project_id=project_id,
                business_name=business_name,
                primary_url=url,
                project_folder=project_root,
                status="needs_review",
                qa_passed=False,
                warnings=warnings,
                errors=["QA engine reported viewport failures"],
            )
        _record_job_transition(
            conn, project_id=project_id, module_name="qa_engine", status="completed"
        )

        # Step 8: Compile delivery/approved-homepage.html and scoped delivery/ghl-ready.html
        _record_job_transition(
            conn, project_id=project_id, module_name="ghl_exporter", status="running"
        )
        _build_standalone_approved_homepage(project_root)
        export_ghl_snippet(project_root, business_id=project_id)
        _record_job_transition(
            conn, project_id=project_id, module_name="ghl_exporter", status="completed"
        )

        # Step 9: Update SQLite project status to completed atomically
        upsert_project(
            conn,
            ProjectRecord(
                project_id=project_id,
                business_name=business_name,
                primary_url=url,
                status="completed",
            ),
        )
        return PipelineRunResult(
            project_id=project_id,
            business_name=business_name,
            primary_url=url,
            project_folder=project_root,
            status="completed",
            qa_passed=True,
            warnings=warnings,
            errors=errors,
        )
    except Exception as exc:
        errors.append(str(exc))
        upsert_project(
            conn,
            ProjectRecord(
                project_id=project_id,
                business_name=business_name,
                primary_url=url,
                status="failed",
            ),
        )
        raise
    finally:
        conn.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EditVista Pet Grooming Website Builder Engine Master Orchestrator Pipeline."
    )
    parser.add_argument("--url", required=True, help="Target business website URL")
    parser.add_argument("--name", required=True, help="Business name")
    parser.add_argument("--business-id", default=None, help="Optional explicit business slug ID")
    parser.add_argument(
        "--projects-dir",
        default="./projects",
        help="Root directory for project workspaces",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Optional explicit SQLite database path",
    )
    parser.add_argument(
        "--allow-private",
        action="store_true",
        help="Allow private/loopback addresses for local testing fixtures",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    qa_runner: QARunnerFn | None = None,
) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    result = run_pipeline(
        url=args.url,
        business_name=args.name,
        business_id=args.business_id,
        projects_dir=args.projects_dir,
        db_path=args.db_path,
        allow_private=bool(args.allow_private),
        qa_runner=qa_runner,
    )
    return 0 if result.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

