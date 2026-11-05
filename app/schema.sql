-- EditVista Pet Grooming Website Builder Engine — Relational SQLite Schema

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    business_name TEXT NOT NULL,
    primary_url TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    module_name TEXT NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_runs_project_id ON job_runs(project_id);

CREATE TABLE IF NOT EXISTS asset_provenance (
    asset_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    sha256_hash TEXT NOT NULL,
    phash TEXT,
    source_url TEXT NOT NULL,
    local_path TEXT NOT NULL,
    rights_confirmed_for_preview INTEGER NOT NULL DEFAULT 0
        CHECK (rights_confirmed_for_preview IN (0, 1)),
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_asset_provenance_project_id ON asset_provenance(project_id);
CREATE INDEX IF NOT EXISTS idx_asset_provenance_sha256 ON asset_provenance(sha256_hash);

CREATE TABLE IF NOT EXISTS business_facts (
    fact_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    category TEXT NOT NULL,
    claim_key TEXT NOT NULL,
    claim_value TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_text_snippet TEXT NOT NULL,
    is_verified INTEGER NOT NULL DEFAULT 0
        CHECK (is_verified IN (0, 1)),
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_business_facts_project_id ON business_facts(project_id);

