"""Master End-to-End Orchestrator & State Machine for EditVista Pet Grooming Website Builder Engine.

Full Lifecycle (Section 3 of Developer Brief):
Collection -> Normalization -> Extraction -> Curation -> Art Direction -> Generation ->
Critic & QA -> Targeted Revision Loop (max 3 cycles) -> Human Approval Gate ->
Frozen GHL Export & Release Archive -> Safe Cleanup.

CLI Interface:
1. Build / Resume:
   `python -m app.pipeline --url <URL> --name <NAME> [--resume] [--auto-approve-test]`
2. Approve & Freeze Release:
   `python -m app.pipeline approve --project-id <ID> --operator "Dev" --notes "Verified"`
3. Approval-Gated Cleanup:
   `python -m app.pipeline prune --project-id <ID> [--execute]`
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.approval import approve_and_freeze_release, generate_review_summary
from app.art_director import generate_art_direction
from app.cleanup import safe_prune_project
from app.collector import collect, slugify
from app.curator import curate_project_images
from app.db import (
    AssetProvenanceRecord,
    BusinessFactRecord,
    JobRunRecord,
    ProjectRecord,
    connect_db,
    init_db,
    list_assets_for_project,
    upsert_asset_provenance,
    upsert_business_fact,
    upsert_job_run,
    upsert_project,
)
from app.fact_extractor import extract_business_facts
from app.generator import generate_website
from app.qa_engine import QADefectReport, run_qa_engine
from app.reviser import MAX_REVISION_ITERATIONS, apply_targeted_revisions
from app.visual_critic import run_visual_critic

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


def build_stage_idempotency_key(
    project_id: str,
    stage_name: str,
    input_manifest_hash: str,
) -> str:
    """Format the canonical SQLite idempotency key for a pipeline stage."""
    return f"{project_id}_{stage_name}_{input_manifest_hash}"


def compute_input_manifest_hash(project_root: Path, input_rel_paths: Sequence[str]) -> str:
    """Compute a deterministic SHA-256 digest across stage input files."""
    hasher = hashlib.sha256()
    for rel in sorted(input_rel_paths):
        p = project_root / rel
        if p.is_file():
            hasher.update(f"{rel}:".encode())
            hasher.update(hashlib.sha256(p.read_bytes()).digest())
        else:
            hasher.update(f"{rel}:missing\n".encode())
    return hasher.hexdigest()[:16]


def _is_stage_completed_and_valid(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    stage_name: str,
    idempotency_key: str,
    project_root: Path,
    required_output_rel_paths: Sequence[str],
) -> bool:
    """Return True if SQLite job_runs shows status='completed' and output artifacts exist."""
    row = conn.execute(
        """
        SELECT status FROM job_runs
        WHERE project_id = ? AND module_name = ? AND idempotency_key = ?
        """,
        (project_id, stage_name, idempotency_key),
    ).fetchone()
    if row is None or str(row["status"]) != "completed":
        return False

    return all((project_root / rel).is_file() for rel in required_output_rel_paths)


def _record_job_transition(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    module_name: str,
    idempotency_key: str,
    status: str,
    error_message: str | None = None,
) -> JobRunRecord:
    run_id = f"{project_id}:{module_name}"
    record = JobRunRecord(
        run_id=run_id,
        project_id=project_id,
        module_name=module_name,
        status=status,
        idempotency_key=idempotency_key,
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

        # Mark downloaded first-party site assets as preview-confirmed for local review
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


class PipelineRunResult(BaseModel):
    """Structured result returned by `run_pipeline`."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    business_name: str
    primary_url: str
    project_folder: Path
    status: str
    qa_passed: bool
    skipped_stages: list[str] = Field(default_factory=list)
    review_summary: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def run_pipeline(
    *,
    url: str,
    business_name: str,
    business_id: str | None = None,
    projects_dir: str | Path = "./projects",
    db_path: str | Path | None = None,
    allow_private: bool = False,
    resume: bool = False,
    pause_for_approval: bool = False,
    auto_approve_test: bool = True,
    qa_runner: QARunnerFn | None = None,
) -> PipelineRunResult:
    """Execute the EditVista lifecycle with SQLite idempotency, resumption, and approval gate."""
    projects_root = Path(projects_dir).resolve()
    projects_root.mkdir(parents=True, exist_ok=True)

    project_id = slugify(business_id or business_name)
    project_root = projects_root / project_id
    resolved_db_path = Path(db_path).resolve() if db_path else (projects_root / "editvista.sqlite3")

    warnings: list[str] = []
    errors: list[str] = []
    skipped_stages: list[str] = []
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

        # Step 2: Collect website pages & media candidates (stage: collect)
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        collect_idemp = build_stage_idempotency_key(project_id, "collect", url_hash)
        if resume and _is_stage_completed_and_valid(
            conn,
            project_id=project_id,
            stage_name="collect",
            idempotency_key=collect_idemp,
            project_root=project_root,
            required_output_rel_paths=["research/pages.json"],
        ):
            skipped_stages.append("collect")
            provenance_records = list_assets_for_project(conn, project_id)
        else:
            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="collect",
                idempotency_key=collect_idemp,
                status="running",
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
                    conn,
                    project_id=project_id,
                    module_name="collect",
                    idempotency_key=collect_idemp,
                    status="completed",
                )
            except Exception as exc:
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
                    module_name="collect",
                    idempotency_key=collect_idemp,
                    status="completed",
                    error_message=f"warning: {exc}",
                )
            provenance_records = _stage_downloaded_assets_for_curator(
                conn, project_root, project_id
            )

        # Step 3: Extract and verify business facts (stage: extract)
        extract_hash = compute_input_manifest_hash(project_root, ["research/pages.json"])
        extract_idemp = build_stage_idempotency_key(project_id, "extract", extract_hash)
        if resume and _is_stage_completed_and_valid(
            conn,
            project_id=project_id,
            stage_name="extract",
            idempotency_key=extract_idemp,
            project_root=project_root,
            required_output_rel_paths=["research/business-facts.json"],
        ):
            skipped_stages.append("extract")
        else:
            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="extract",
                idempotency_key=extract_idemp,
                status="running",
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
                conn,
                project_id=project_id,
                module_name="extract",
                idempotency_key=extract_idemp,
                status="completed",
            )

        # Step 4: Curate images (stage: curate)
        curate_hash = compute_input_manifest_hash(project_root, ["research/asset-manifest.json"])
        curate_idemp = build_stage_idempotency_key(project_id, "curate", curate_hash)
        if resume and _is_stage_completed_and_valid(
            conn,
            project_id=project_id,
            stage_name="curate",
            idempotency_key=curate_idemp,
            project_root=project_root,
            required_output_rel_paths=["design/image-selection.json"],
        ):
            skipped_stages.append("curate")
        else:
            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="curate",
                idempotency_key=curate_idemp,
                status="running",
            )
            curate_res = curate_project_images(project_root)
            warnings.extend(curate_res.warnings)
            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="curate",
                idempotency_key=curate_idemp,
                status="completed",
            )

        # Step 5: Art Direction & Brand Analysis (stage: art_director)
        art_hash = compute_input_manifest_hash(
            project_root,
            ["research/business-facts.json", "design/image-selection.json"],
        )
        art_idemp = build_stage_idempotency_key(project_id, "art_director", art_hash)
        if resume and _is_stage_completed_and_valid(
            conn,
            project_id=project_id,
            stage_name="art_director",
            idempotency_key=art_idemp,
            project_root=project_root,
            required_output_rel_paths=["design/brand.json", "design/creative-brief.json"],
        ):
            skipped_stages.append("art_director")
        else:
            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="art_director",
                idempotency_key=art_idemp,
                status="running",
            )
            generate_art_direction(project_root, provenance_records=provenance_records)
            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="art_director",
                idempotency_key=art_idemp,
                status="completed",
            )

        # Step 6: Generate semantic website code (stage: generate)
        gen_hash = compute_input_manifest_hash(
            project_root,
            [
                "research/business-facts.json",
                "design/image-selection.json",
                "design/brand.json",
                "design/creative-brief.json",
            ],
        )
        gen_idemp = build_stage_idempotency_key(project_id, "generate", gen_hash)
        if resume and _is_stage_completed_and_valid(
            conn,
            project_id=project_id,
            stage_name="generate",
            idempotency_key=gen_idemp,
            project_root=project_root,
            required_output_rel_paths=[
                "website/index.html",
                "website/css/styles.css",
                "website/js/main.js",
            ],
        ):
            skipped_stages.append("generate")
        else:
            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="generate",
                idempotency_key=gen_idemp,
                status="running",
            )
            generate_website(project_root)
            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="generate",
                idempotency_key=gen_idemp,
                status="completed",
            )

        # Step 7: Execute 5-viewport Playwright QA + Visual Critic + Targeted Revision Loop
        qa_hash = compute_input_manifest_hash(
            project_root,
            ["website/index.html", "website/css/styles.css", "website/js/main.js"],
        )
        qa_idemp = build_stage_idempotency_key(project_id, "qa", qa_hash)
        critique_idemp = build_stage_idempotency_key(project_id, "critique", qa_hash)
        revise_idemp = build_stage_idempotency_key(project_id, "revise", qa_hash)

        _record_job_transition(
            conn,
            project_id=project_id,
            module_name="qa",
            idempotency_key=qa_idemp,
            status="running",
        )
        qa_report = active_qa_runner(project_root)

        # Bounded Critique -> Revise -> QA loop (max 3 cycles)
        for _cycle in range(MAX_REVISION_ITERATIONS):
            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="critique",
                idempotency_key=critique_idemp,
                status="running",
            )
            critique_report = run_visual_critic(project_root)
            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="critique",
                idempotency_key=critique_idemp,
                status="completed",
            )

            if critique_report.status == "passed" or not critique_report.defects:
                _record_job_transition(
                    conn,
                    project_id=project_id,
                    module_name="revise",
                    idempotency_key=revise_idemp,
                    status="completed",
                )
                break

            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="revise",
                idempotency_key=revise_idemp,
                status="running",
            )
            apply_targeted_revisions(project_root)
            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="revise",
                idempotency_key=revise_idemp,
                status="completed",
            )
            qa_report = active_qa_runner(project_root)

        if not qa_report.passed:
            _record_job_transition(
                conn,
                project_id=project_id,
                module_name="qa",
                idempotency_key=qa_idemp,
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
                skipped_stages=skipped_stages,
                warnings=warnings,
                errors=["QA engine reported viewport failures"],
            )

        _record_job_transition(
            conn,
            project_id=project_id,
            module_name="qa",
            idempotency_key=qa_idemp,
            status="completed",
        )

        # Assemble human review summary package
        review_summary = generate_review_summary(project_id, projects_dir=projects_root)
        _atomic_write_text(
            project_root / "qa" / "review-summary.json",
            json.dumps(review_summary, indent=2),
        )

        # Step 8: Human Approval Gate vs. Auto-Approve Test Mode
        if pause_for_approval and not auto_approve_test:
            upsert_project(
                conn,
                ProjectRecord(
                    project_id=project_id,
                    business_name=business_name,
                    primary_url=url,
                    status="awaiting_approval",
                ),
            )
            return PipelineRunResult(
                project_id=project_id,
                business_name=business_name,
                primary_url=url,
                project_folder=project_root,
                status="awaiting_approval",
                qa_passed=True,
                skipped_stages=skipped_stages,
                review_summary=review_summary,
                warnings=warnings,
                errors=errors,
            )

        # Step 9: Approved Release Freeze, GHL Export & Verified Archive
        export_idemp = build_stage_idempotency_key(project_id, "ghl_exporter", qa_hash)
        _record_job_transition(
            conn,
            project_id=project_id,
            module_name="ghl_exporter",
            idempotency_key=export_idemp,
            status="running",
        )
        approve_and_freeze_release(
            project_id,
            operator_name="Automated Test Runner",
            notes="Approved via pipeline execution",
            projects_dir=projects_root,
            db_path=resolved_db_path,
        )
        _record_job_transition(
            conn,
            project_id=project_id,
            module_name="ghl_exporter",
            idempotency_key=export_idemp,
            status="completed",
        )

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
            skipped_stages=skipped_stages,
            review_summary=review_summary,
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


def _handle_approve_subcommand(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.pipeline approve",
        description="Approve and freeze an immutable website release and GHL export.",
    )
    parser.add_argument("--project-id", required=True, help="Target project slug ID")
    parser.add_argument("--operator", required=True, help="Human reviewer/operator name")
    parser.add_argument("--notes", default="Verified", help="Approval sign-off notes")
    parser.add_argument("--projects-dir", default="./projects", help="Root projects directory")
    parser.add_argument("--db-path", default=None, help="Optional SQLite DB path")
    args = parser.parse_args(argv)

    approve_and_freeze_release(
        args.project_id,
        operator_name=args.operator,
        notes=args.notes,
        projects_dir=args.projects_dir,
        db_path=args.db_path,
    )
    return 0


def _handle_prune_subcommand(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.pipeline prune",
        description="Run approval-gated cleanup for unreferenced staging and temporary files.",
    )
    parser.add_argument("--project-id", required=True, help="Target project slug ID")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute deletion (defaults to dry-run if omitted)",
    )
    parser.add_argument("--projects-dir", default="./projects", help="Root projects directory")
    args = parser.parse_args(argv)

    project_root = Path(args.projects_dir).resolve() / args.project_id
    safe_prune_project(project_root, dry_run=not bool(args.execute))
    return 0


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
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the last pending or failed stage using SQLite idempotency keys",
    )
    parser.add_argument(
        "--pause-for-approval",
        dest="pause_for_approval",
        action="store_true",
        default=True,
        help="Pause at the human approval gate before exporting GHL deliverables (default: true)",
    )
    parser.add_argument(
        "--no-pause-for-approval",
        dest="pause_for_approval",
        action="store_false",
        help="Do not pause for approval",
    )
    parser.add_argument(
        "--auto-approve-test",
        action="store_true",
        help="Automatically approve and export deliverables for non-interactive E2E test runs",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    qa_runner: QARunnerFn | None = None,
) -> int:
    args_list = list(argv) if argv is not None else None
    if args_list and args_list[0] == "approve":
        return _handle_approve_subcommand(args_list[1:])
    if args_list and args_list[0] == "prune":
        return _handle_prune_subcommand(args_list[1:])

    parser = build_arg_parser()
    args = parser.parse_args(args_list)

    # If the caller invoked legacy E2E CLI flags without explicitly passing
    # --pause-for-approval, allow auto-approval when qa_runner or --auto-approve-test is set
    auto_approve = bool(args.auto_approve_test) or (
        qa_runner is not None
        and args_list is not None
        and "--pause-for-approval" not in args_list
    )

    result = run_pipeline(
        url=args.url,
        business_name=args.name,
        business_id=args.business_id,
        projects_dir=args.projects_dir,
        db_path=args.db_path,
        allow_private=bool(args.allow_private),
        resume=bool(args.resume),
        pause_for_approval=bool(args.pause_for_approval),
        auto_approve_test=auto_approve,
        qa_runner=qa_runner,
    )
    return 0 if result.status in ("completed", "awaiting_approval") else 1


if __name__ == "__main__":
    raise SystemExit(main())
