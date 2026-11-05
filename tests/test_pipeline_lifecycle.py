"""Lifecycle, resumption, idempotency, and approval gate tests for app/pipeline.py."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from app.db import connect_db, get_project
from app.pipeline import build_stage_idempotency_key, main, run_pipeline
from app.qa_engine import BREAKPOINTS, QADefectReport, ViewportQAResult
from PIL import Image, ImageDraw
from tests.test_pipeline_e2e import _ephemeral_grooming_salon_server


def _mock_png_bytes(width: int = 320, height: int = 200) -> bytes:
    img = Image.new("RGB", (width, height), color=(27, 54, 93))
    draw = ImageDraw.Draw(img)
    draw.rectangle((20, 20, width - 20, height - 20), fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fast_qa_runner(project_folder: str | Path, **_kwargs: Any) -> QADefectReport:
    project_root = Path(project_folder).resolve()
    screenshots_dir = project_root / "qa" / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    viewports: list[ViewportQAResult] = []
    for label, width in BREAKPOINTS:
        shot = screenshots_dir / f"{width}px.png"
        shot.write_bytes(_mock_png_bytes())
        viewports.append(
            ViewportQAResult(
                label=label,
                width=width,
                screenshot_path=shot.relative_to(project_root).as_posix(),
                horizontal_overflow=False,
                scroll_width=width,
                inner_width=width,
                broken_assets=[],
                console_errors=[],
                contrast_failures=[],
                passed=True,
            )
        )
    report = QADefectReport(
        project_id=project_root.name,
        target_url=f"http://localhost/{project_root.name}/website/index.html",
        passed=True,
        viewports=viewports,
    )
    (project_root / "qa" / "qa-report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )
    return report


def test_pipeline_resumption_skips_completed_stages_after_curation(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """Simulate an aborted job after curation; --resume skips collect/extract/curate."""
    projects_dir = tmp_path / "projects"
    db_path = projects_dir / "editvista.sqlite3"
    biz_id = "resume-paws-salon"

    collect_calls = 0
    extract_calls = 0
    curate_calls = 0

    import app.pipeline as pipeline_mod

    orig_collect = pipeline_mod.collect
    orig_extract = pipeline_mod.extract_business_facts
    orig_curate = pipeline_mod.curate_project_images

    def tracked_collect(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal collect_calls
        collect_calls += 1
        return orig_collect(*args, **kwargs)

    def tracked_extract(*args: Any, **kwargs: Any) -> Any:
        nonlocal extract_calls
        extract_calls += 1
        return orig_extract(*args, **kwargs)

    def tracked_curate(*args: Any, **kwargs: Any) -> Any:
        nonlocal curate_calls
        curate_calls += 1
        return orig_curate(*args, **kwargs)

    monkeypatch.setattr(pipeline_mod, "collect", tracked_collect)
    monkeypatch.setattr(pipeline_mod, "extract_business_facts", tracked_extract)
    monkeypatch.setattr(pipeline_mod, "curate_project_images", tracked_curate)

    with _ephemeral_grooming_salon_server() as target_url:
        # 1. First run: simulate crash at art_director (after collect, extract, curate succeed)
        orig_art = pipeline_mod.generate_art_direction

        def crashing_art_director(*_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("Simulated mid-pipeline crash after curation")

        monkeypatch.setattr(pipeline_mod, "generate_art_direction", crashing_art_director)

        try:
            run_pipeline(
                url=target_url,
                business_name="Resume Paws Salon",
                business_id=biz_id,
                projects_dir=projects_dir,
                db_path=db_path,
                allow_private=True,
                pause_for_approval=False,
                auto_approve_test=True,
                qa_runner=_fast_qa_runner,
            )
        except RuntimeError:
            pass

        assert collect_calls == 1
        assert extract_calls == 1
        assert curate_calls == 1

        # Restore working art_director and run via CLI with --resume and --auto-approve-test
        monkeypatch.setattr(pipeline_mod, "generate_art_direction", orig_art)

        exit_code = main(
            [
                "--url",
                target_url,
                "--name",
                "Resume Paws Salon",
                "--business-id",
                biz_id,
                "--projects-dir",
                str(projects_dir),
                "--db-path",
                str(db_path),
                "--allow-private",
                "--resume",
                "--auto-approve-test",
            ],
            qa_runner=_fast_qa_runner,
        )
        assert exit_code == 0

    # Assert earlier completed stages (collect, extract, curate) were NOT re-executed
    assert collect_calls == 1
    assert extract_calls == 1
    assert curate_calls == 1

    # Verify idempotency key format: f"{project_id}_{stage_name}_{input_manifest_hash}"
    sample_key = build_stage_idempotency_key(biz_id, "curate", "abc123manifest")
    assert sample_key == f"{biz_id}_curate_abc123manifest"


def test_pipeline_pauses_at_approval_gate_and_unlocks_on_cli_approve_and_prune(
    tmp_path: Path,
) -> None:
    """Verify ghl-ready.html is blocked when paused for approval, then built on CLI approve."""
    projects_dir = tmp_path / "projects"
    db_path = projects_dir / "editvista.sqlite3"
    biz_id = "gated-salon"

    with _ephemeral_grooming_salon_server() as target_url:
        # Run with default pause_for_approval=True (no --auto-approve-test)
        res = run_pipeline(
            url=target_url,
            business_name="Gated Pet Salon",
            business_id=biz_id,
            projects_dir=projects_dir,
            db_path=db_path,
            allow_private=True,
            pause_for_approval=True,
            auto_approve_test=False,
            qa_runner=_fast_qa_runner,
        )

    project_root = projects_dir / biz_id
    ghl_path = project_root / "delivery" / "ghl-ready.html"
    archive_zip = projects_dir / "_archives" / f"{biz_id}-approved.zip"

    # 1. Pipeline pauses at awaiting_approval; ghl-ready.html and archive ZIP are NOT yet created
    assert res.status == "awaiting_approval"
    assert (project_root / "website" / "index.html").is_file()
    assert (project_root / "qa" / "visual-critique.json").is_file()
    assert not ghl_path.exists()
    assert not archive_zip.exists()

    # 2. Execute CLI subcommand: `python -m app.pipeline approve --project-id <ID> ...`
    approve_exit = main(
        [
            "approve",
            "--project-id",
            biz_id,
            "--operator",
            "Dev",
            "--notes",
            "Verified",
            "--projects-dir",
            str(projects_dir),
            "--db-path",
            str(db_path),
        ]
    )
    assert approve_exit == 0
    assert ghl_path.is_file()
    assert archive_zip.is_file()

    conn = connect_db(db_path)
    try:
        proj = get_project(conn, biz_id)
        assert proj is not None
        assert proj.status == "approved"
    finally:
        conn.close()

    # 3. Execute CLI subcommand: `python -m app.pipeline prune --project-id <ID> --execute`
    (project_root / "tmp").mkdir(parents=True, exist_ok=True)
    temp_junk = project_root / "tmp" / "scratch.tmp"
    temp_junk.write_bytes(b"junk")

    prune_exit = main(
        [
            "prune",
            "--project-id",
            biz_id,
            "--execute",
            "--projects-dir",
            str(projects_dir),
        ]
    )
    assert prune_exit == 0
    assert not temp_junk.exists()
    assert ghl_path.is_file()
