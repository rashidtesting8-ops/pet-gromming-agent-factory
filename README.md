# Pet Grooming Website Builder Engine (EditVista)

A local-first, provenance-driven Python engine for collecting, verifying, curating, auditing, and exporting bespoke pet grooming websites (standalone HTML + GoHighLevel-ready snippets).

> **Status:** Prototype & testing engine (`Python 3.12`, `uv`, `Pydantic v2`). No paid hosting or external cloud database is required to run collection, local QA, or export workflows.

---

## Core Engineering & Domain Principles

Every module in this repository enforces the non-negotiable rules defined in [`AGENTS.md`](./AGENTS.md) and [`docs/DEVELOPER_BRIEF.md`](./docs/DEVELOPER_BRIEF.md):

1. **Zero Fabrication:** Never invent business facts, logos, owner portraits, reviews, ratings, prices, discounts, or services. Missing or unverified claims default to `status="needs_review"`.
2. **Untrusted External Input:** All text scraped from websites, social captions, or image metadata is treated strictly as **data**, never as instructions.
3. **Full Claim & Asset Provenance:**
   - Every [`Claim`](./src/engine/contracts/__init__.py) requires `source_url`, non-empty `source_text`, `verified`, `status` (`verified | needs_review | expired`), and timezone-aware `last_checked_at`.
   - Every [`Asset`](./src/engine/contracts/__init__.py) records `source_url`, `sha256`, timezone-aware `captured_at`, and `rights_confirmed_for_preview` (defaults to `False`).
   - Every fetched webpage's raw HTML is archived at `<project>/research/snapshots/<sha256>.html` and indexed in `research/pages.json`.
4. **SSRF & DNS Rebinding Protection:** Website HTTP connections use a scoped `SafeHTTPAdapter` and custom socket dialer that resolves DNS **once** per hop, validates **all** returned records against private/loopback/link-local/CGNAT/metadata IP ranges (including IPv4-mapped IPv6 and hex/octal/integer IP literals), disables environment proxies (`trust_env = False`), and validates every redirect hop manually while preserving the original `Host` header and TLS SNI.
5. **Privacy & EXIF/GPS Stripping:** Social media collection (`gallery-dl` subprocess) and Meta export imports strip all EXIF/GPS metadata on optimized image copies under `assets/optimized/` and scrub sensitive tokens from logs.
6. **Mandatory Release Gate & Immutable Deliverables:** The exporter ([`src/engine/exporter.py`](./src/engine/exporter.py)) refuses to build `delivery/approved-homepage.html` or `delivery/ghl-ready.html` if **any** asset referenced in the page has `rights_confirmed_for_preview=False` or is missing from project manifests. Once created, approved releases under `delivery/` are immutable.

---

## Repository Structure

```text
pet-gromming-agent-factory/
├── AGENTS.md                        # Non-negotiable domain and engineering rules
├── pyproject.toml                   # Python 3.12 / uv config, pinned deps, ruff/pyright/pytest
├── Makefile / justfile              # Task runners: lint, typecheck, test
├── requirements.txt                 # Core runtime dependencies
├── requirements-social.txt          # Optional pinned gallery-dl==1.30.0 subprocess dependency
├── requirements-browser.txt         # Optional pinned playwright==1.52.0 browser QA dependency
├── .github/workflows/ci.yml         # GitHub Actions CI (ruff, pyright, pytest)
├── docs/
│   ├── DEVELOPER_BRIEF.md           # Full technical implementation specification (v1.1)
│   ├── HANDOFF_README.md            # Handoff overview
│   ├── AUDIT_AND_TESTS.md           # Audit findings and validation log
│   └── BUDGET_AND_QUALITY.md        # Spend control, quality release gates, and resource policy
├── examples/
│   └── BUSINESS_INPUT_EXAMPLE.json  # Example business intake payload
├── src/engine/
│   ├── contracts/                   # Pydantic v2 models: StageInput, StageOutput, Asset, Claim, Warning
│   ├── collector.py                 # SSRF-hardened website crawler, HTML snapshot archiver & asset collector
│   ├── browser_gallery.py           # Optional Playwright JS-rendered gallery candidate extractor
│   ├── social_collect.py            # Hardened gallery-dl subprocess wrapper (dry-run metadata, EXIF strip)
│   ├── import_social_media.py       # Manual authorized social media file importer
│   ├── import_meta_export.py        # Defensive Meta ("Download your information") zip/folder importer
│   ├── contact_sheet.py             # Local photo contact sheet generator for visual curation
│   ├── local_preview.py             # 5-viewport Playwright & static HTML technical/accessibility QA
│   ├── exporter.py                  # Release-gated standalone HTML & GoHighLevel snippet exporter
│   ├── cleanup.py                   # Approval-gated SHA-256 verified zip archiver and selective pruner
│   └── service.py                   # Local FastAPI job server backed by durable SQLite state
├── app/                             # Backward-compatible CLI/Docker shims re-exporting src/engine/*
├── n8n/
│   ├── 01-submit-asset-research.json
│   └── 02-check-asset-job.json
└── tests/
    ├── test_contracts.py            # Pydantic v2 contract validation tests
    ├── test_collector.py            # Website crawl, raw HTML snapshots, and asset provenance tests
    ├── test_ssrf_rebinding.py       # DNS rebinding, private IP, encoded literal, and redirect SSRF tests
    ├── test_social_collect.py       # Subprocess dry-run metadata, EXIF/GPS strip, failure classifier tests
    ├── test_import_meta_export.py   # Instagram/Facebook export parser, zip-bomb & traversal guard tests
    ├── test_local_preview.py        # CTA/nav link validation, mobile menu, and reduced-motion QA tests
    ├── test_exporter_release_gate.py# Release gate & immutability tests for approved/GHL deliverables
    └── test_v2.py                   # End-to-end v2 workflow compatibility and cleanup tests
```

---

## Per-Project Workspace Layout

Each business run operates inside an isolated project folder under `projects/<business-slug>/`:

```text
projects/<business-slug>/
├── assets/
│   ├── website/                     # Original website images/logos/videos
│   ├── instagram/                   # Raw collected/imported Instagram media
│   ├── facebook/                    # Raw collected/imported Facebook media
│   └── optimized/                   # EXIF/GPS-stripped optimized images
├── research/
│   ├── snapshots/<sha256>.html      # Immutable raw HTML snapshots for claim verification
│   ├── pages.json                   # Crawled page metadata (url, sha256, fetched_at, status_code, text)
│   ├── asset-manifest.json          # Provenance-tracked asset manifest
│   ├── social-media-manifest.json   # Social media provenance manifest
│   ├── meta-export-import-log.json  # Defensive parser log (including unparsed entries & reasons)
│   └── run-summary.json             # Crawl summary and diagnostics
├── website/
│   └── index.html                   # Candidate homepage under design/review
├── qa/
│   ├── screenshots/                 # 1440w, 1024w, 768w, 390w, 360w viewport renders
│   └── qa-report.json               # Technical QA report (badLinks, mobileMenu, reducedMotion, overflow)
└── delivery/                        # Populated ONLY after passing the exporter release gate
    ├── approved-homepage.html       # Immutable standalone HTML deliverable
    ├── ghl-ready.html               # Scoped GoHighLevel custom HTML/CSS/JS snippet
    ├── retained-assets.json         # Approved retained asset list
    ├── asset-manifest.json          # Selected asset provenance map
    └── release-manifest.json        # Release timestamp and SHA-256 checksums
```

---

## Quickstart & Development Workflow

### Prerequisites
- **Python 3.12**
- **[`uv`](https://docs.astral.sh/uv/)** package and environment manager

### Install & Verify
```bash
# Install dependencies into .venv
uv sync

# Run the mandatory verification suite (lint + typecheck + test)
uv run ruff check . && uv run pyright && uv run pytest -v
```

You can also use `make` or `just`:
```bash
make lint
make typecheck
make test
```

---

## Stage-by-Stage CLI Reference

### 1. Website Collection & Snapshot Archiving
Crawls same-site pages (respecting `robots.txt`, crawl budgets, and SSRF/DNS-rebinding guards), archives raw HTML to `research/snapshots/<sha256>.html`, and downloads candidate media:

```bash
uv run python -m engine.collector https://example-groomer.com --output projects --max-pages 25 --max-media 80
```

### 2. Optional Public Social Media Collection (`gallery-dl` Subprocess)
Requires `gallery-dl==1.30.0` installed on the host (`pip install -r requirements-social.txt`) and an explicit `--i-have-permission` flag. Runs a `--dump-json` metadata dry-run first, verifies real timestamps, strips EXIF/GPS into `assets/optimized/`, and classifies any failure (`login_required`, `rate_limited`, `extractor_broken`, `unknown`) into `status="review_needed"` without raising:

```bash
uv run python -m engine.social_collect \
  --project projects/example-groomer-com \
  --platform instagram \
  --url https://www.instagram.com/example_groomer/ \
  --days 365 \
  --max-files 40 \
  --i-have-permission
```

### 3. Meta ("Download Your Information") Export Importer
Defensively parses an Instagram or Facebook archive (`.zip` or extracted folder) into `research/asset-manifest.json` and `research/social-media-manifest.json`. Guards against zip bombs, spoofed zip headers, symlinks, and path traversal, uses real post timestamps for `captured_at` / `post_date`, sets `rights_confirmed_for_preview=False`, and logs any unparsed items to `research/meta-export-import-log.json`:

```bash
uv run python -m engine.import_meta_export \
  --project projects/example-groomer-com \
  --export /path/to/instagram-export.zip \
  --platform auto \
  --max-files 80
```

### 4. Local Technical & Accessibility QA
Audits `website/index.html` across **1440px, 1024px, 768px, 390px, and 360px** viewports (using Playwright Chromium when installed, plus static HTML/CSS analysis). Fails `technical_pass` if any CTA/nav link is `#`, empty, `javascript:`, or a placeholder (`todo`, `placeholder`, `coming-soon`, `example.com`), or if mobile menu open/close or `@media (prefers-reduced-motion: reduce)` support is missing:

```bash
# Optional: install Chromium for live multi-viewport rendering
uv run playwright install chromium

uv run python -m engine.local_preview --html projects/example-groomer-com/website/index.html
```

### 5. Release Gate & Deliverable Exporter
Verifies that every asset referenced in `website/index.html` exists in the project manifests with `rights_confirmed_for_preview: true`. If any used asset is unconfirmed, export is blocked and the list of `offending_assets` is returned. Once confirmed, builds immutable `delivery/approved-homepage.html` and scoped `delivery/ghl-ready.html`:

```bash
uv run python -m engine.exporter --project projects/example-groomer-com
```

### 6. Post-Approval Verified Archive & Storage Cleanup
Requires `delivery/approved-homepage.html`, `delivery/ghl-ready.html`, and `delivery/retained-assets.json` (`"approved": true`). Creates a CRC- and SHA-256-verified `.zip` archive in `projects/_archives/` before pruning unused raw staging media:

```bash
uv run python -m engine.cleanup --project projects/example-groomer-com --mode plan
uv run python -m engine.cleanup --project projects/example-groomer-com --mode archive
uv run python -m engine.cleanup --project projects/example-groomer-com --mode prune --confirm
```

---

## Local FastAPI Job Service & Docker Compose (Optional)

To run the local SQLite-backed collector API and self-hosted `n8n` orchestrator:

```bash
docker compose up --build -d
```

- **Collector API Swagger UI:** `http://127.0.0.1:8787/docs`
- **n8n UI:** `http://127.0.0.1:5678` (import workflows from [`n8n/`](./n8n/))
