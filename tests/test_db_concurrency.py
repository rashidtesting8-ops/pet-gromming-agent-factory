"""Concurrency, PRAGMA, schema, and Pydantic v2 model tests for app/db.py."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.db import (
    AssetProvenanceRecord,
    BusinessFactRecord,
    JobRunRecord,
    ProjectRecord,
    connect_db,
    get_job_run,
    get_project,
    immediate_transaction,
    init_db,
    list_assets_for_project,
    list_facts_for_project,
    upsert_asset_provenance,
    upsert_business_fact,
    upsert_job_run,
    upsert_project,
)
from pydantic import ValidationError


def test_connection_pragmas_and_schema_initialization(tmp_path: Path) -> None:
    db_path = tmp_path / "editvista.sqlite"
    conn = connect_db(db_path)
    try:
        init_db(conn)

        journal_mode = str(conn.execute("PRAGMA journal_mode;").fetchone()[0]).lower()
        busy_timeout = int(conn.execute("PRAGMA busy_timeout;").fetchone()[0])
        synchronous = int(conn.execute("PRAGMA synchronous;").fetchone()[0])
        foreign_keys = int(conn.execute("PRAGMA foreign_keys;").fetchone()[0])
        temp_store = int(conn.execute("PRAGMA temp_store;").fetchone()[0])

        assert journal_mode == "wal"
        assert busy_timeout == 5000
        # NORMAL synchronous mode in SQLite is 1
        assert synchronous == 1
        assert foreign_keys == 1
        # MEMORY temp_store in SQLite is 2
        assert temp_store == 2
    finally:
        conn.close()


def test_pydantic_models_and_crud_operations(tmp_path: Path) -> None:
    db_path = tmp_path / "crud.sqlite"
    conn = connect_db(db_path)
    try:
        init_db(conn)
        ts = datetime(2026, 11, 5, 10, 0, 0, tzinfo=UTC)

        project = ProjectRecord(
            project_id="proj-1",
            business_name="Paws & Bubbles Salon",
            primary_url="https://pawsandbubbles.example.com",
            status="collecting",
            created_at=ts,
            updated_at=ts,
        )
        upsert_project(conn, project)
        fetched_proj = get_project(conn, "proj-1")
        assert fetched_proj is not None
        assert fetched_proj.business_name == "Paws & Bubbles Salon"

        job = JobRunRecord(
            run_id="run-1",
            project_id="proj-1",
            module_name="website_collector",
            status="completed",
            idempotency_key="proj-1:website_collector:v1",
            error_message=None,
            created_at=ts,
            updated_at=ts,
        )
        upsert_job_run(conn, job)
        fetched_job = get_job_run(conn, "run-1")
        assert fetched_job is not None
        assert fetched_job.idempotency_key == "proj-1:website_collector:v1"

        # AssetProvenanceRecord defaults rights_confirmed_for_preview to False
        asset = AssetProvenanceRecord(
            asset_id="asset-1",
            project_id="proj-1",
            sha256_hash="a" * 64,
            phash="f0f0f0f0f0f0f0f0",
            source_url="https://pawsandbubbles.example.com/dog.jpg",
            local_path="assets/website/dog.jpg",
        )
        assert asset.rights_confirmed_for_preview is False
        upsert_asset_provenance(conn, asset)
        assets = list_assets_for_project(conn, "proj-1")
        assert len(assets) == 1
        assert assets[0].rights_confirmed_for_preview is False

        fact = BusinessFactRecord(
            fact_id="fact-1",
            project_id="proj-1",
            category="pricing",
            claim_key="full_groom_small_dog",
            claim_value="$65",
            source_url="https://pawsandbubbles.example.com/services",
            source_text_snippet="Full Groom (Small Dogs under 20 lbs): $65",
            is_verified=True,
        )
        upsert_business_fact(conn, fact)
        facts = list_facts_for_project(conn, "proj-1")
        assert len(facts) == 1
        assert facts[0].is_verified is True

        # Blank source_text_snippet must fail Pydantic validation
        with pytest.raises(ValidationError):
            BusinessFactRecord(
                fact_id="fact-bad",
                project_id="proj-1",
                category="pricing",
                claim_key="bath",
                claim_value="$40",
                source_url="https://pawsandbubbles.example.com/services",
                source_text_snippet="   ",
                is_verified=False,
            )
    finally:
        conn.close()


def test_ten_concurrent_threads_writing_with_zero_lock_errors(tmp_path: Path) -> None:
    """Spin up 10 concurrent threads writing simultaneously with immediate_transaction."""
    db_path = tmp_path / "concurrent.sqlite"
    setup_conn = connect_db(db_path)
    try:
        init_db(setup_conn)
    finally:
        setup_conn.close()

    num_threads = 10
    writes_per_thread = 15
    errors: list[Exception] = []

    def worker(thread_idx: int) -> int:
        conn = connect_db(db_path)
        completed = 0
        try:
            proj_id = f"proj-{thread_idx}"
            upsert_project(
                conn,
                ProjectRecord(
                    project_id=proj_id,
                    business_name=f"Salon {thread_idx}",
                    primary_url=f"https://salon-{thread_idx}.example.com",
                    status="running",
                ),
            )
            for i in range(writes_per_thread):
                run_id = f"run-{thread_idx}-{i}"
                asset_id = f"asset-{thread_idx}-{i}"
                fact_id = f"fact-{thread_idx}-{i}"
                now_iso = datetime.now(UTC).isoformat()

                with immediate_transaction(conn):
                    conn.execute(
                        """
                        INSERT INTO job_runs (
                            run_id, project_id, module_name, status,
                            idempotency_key, error_message, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            proj_id,
                            "collector",
                            "done",
                            f"idem-{thread_idx}-{i}",
                            None,
                            now_iso,
                            now_iso,
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO asset_provenance (
                            asset_id, project_id, sha256_hash, phash,
                            source_url, local_path, rights_confirmed_for_preview
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            asset_id,
                            proj_id,
                            f"{thread_idx:02x}{i:02x}" + ("b" * 60),
                            "0011223344556677",
                            f"https://salon-{thread_idx}.example.com/img-{i}.jpg",
                            f"assets/website/img-{thread_idx}-{i}.jpg",
                            0,
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO business_facts (
                            fact_id, project_id, category, claim_key,
                            claim_value, source_url, source_text_snippet, is_verified
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            fact_id,
                            proj_id,
                            "services",
                            f"service_{i}",
                            "Nail Trim",
                            f"https://salon-{thread_idx}.example.com/services",
                            "We offer gentle nail trims for all breeds.",
                            1,
                        ),
                    )
                completed += 1
        finally:
            conn.close()
        return completed

    with ThreadPoolExecutor(max_workers=num_threads) as pool:
        futures = [pool.submit(worker, idx) for idx in range(num_threads)]
        total_completed = 0
        for fut in as_completed(futures):
            try:
                total_completed += fut.result()
            except Exception as exc:
                errors.append(exc)

    assert errors == [], f"Expected zero lock errors, got: {errors}"
    assert total_completed == num_threads * writes_per_thread

    verify_conn = connect_db(db_path)
    try:
        proj_count = int(verify_conn.execute("SELECT COUNT(*) FROM projects;").fetchone()[0])
        run_count = int(verify_conn.execute("SELECT COUNT(*) FROM job_runs;").fetchone()[0])
        asset_count = int(
            verify_conn.execute("SELECT COUNT(*) FROM asset_provenance;").fetchone()[0]
        )
        fact_count = int(verify_conn.execute("SELECT COUNT(*) FROM business_facts;").fetchone()[0])

        assert proj_count == num_threads
        assert run_count == num_threads * writes_per_thread
        assert asset_count == num_threads * writes_per_thread
        assert fact_count == num_threads * writes_per_thread
    finally:
        verify_conn.close()
