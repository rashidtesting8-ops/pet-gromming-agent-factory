# Pet Grooming Engine — Local Collector v2 & Website Builder Foundation

**This is the asset/research/QA foundation and contract-driven engine for EditVista's Pet Grooming Website Builder.** No paid platform or preview hosting is needed to run it locally.

## Project structure

```text
pet-gromming-agent-factory/
  AGENTS.md                  # Engineering and non-negotiable domain rules
  pyproject.toml             # uv / Python 3.12 configuration, pinned dependencies, ruff/pyright/pytest
  docs/
    DEVELOPER_BRIEF.md       # Full technical implementation specification (v1.1)
    HANDOFF_README.md        # Developer handoff package guide
    AUDIT_AND_TESTS.md       # Module 01 v2 audit findings and validation log
    BUDGET_AND_QUALITY.md    # Spend control, quality release gates, and resource policy
  examples/
    BUSINESS_INPUT_EXAMPLE.json
  src/engine/
    contracts/               # Pydantic v2 stage I/O, provenance, claim, asset, and intake contracts
    collector.py             # Bounded static website collection and content extraction
    browser_gallery.py       # Optional Playwright JS-rendered gallery candidate extraction
    social_collect.py        # Opt-in gallery-dl wrapper for eligible public social media
    import_social_media.py   # Manual client/authorized social media import with provenance
    contact_sheet.py         # Local photo contact sheet generator
    local_preview.py         # Playwright 5-width screenshot / broken-image / overflow QA
    cleanup.py               # Approval-gated SHA256-verified archive and selective pruning
    service.py               # Local FastAPI job service backed by durable SQLite state
  app/                       # Backward-compatible CLI/Docker shims re-exporting src.engine.*
  n8n/
    01-submit-asset-research.json
    02-check-asset-job.json
  tests/
    test_contracts.py        # Pydantic v2 contract, provenance, and atomic write tests
    test_collector.py        # Website crawl, deduplication, and social import tests
    test_v2.py               # Social host validation, date cutoffs, and safe cleanup tests
```

## Quickstart with `uv` (Recommended — Python 3.12)

```bash
uv sync
uv run ruff check .
uv run pyright
uv run pytest
```

Run the website collector:

```bash
uv run python -m app.collector https://example-groomer.com --output projects
```

## Setup without `uv` / Docker / n8n

Requires Python 3.11+ (Python 3.12 recommended).

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m app.collector https://example-groomer.com --output projects
```

Output: `projects/example-groomer-com/`. Replace example URL with an actual permitted public business website. You can double-click a complete self-contained `index.html` once the designer has created it. The collector does **not** generate HTML by itself.

## Optional social collection

```bash
pip install -r requirements-social.txt
python -m app.social_collect --project projects/example-groomer-com --platform instagram --url https://www.instagram.com/EXAMPLE/ --days 365 --max-files 40
python -m app.social_collect --project projects/example-groomer-com --platform facebook --url https://www.facebook.com/EXAMPLE/ --days 365 --max-files 40
```

Source: `gallery-dl` open-source Instagram and Facebook extractors. Public availability **does not imply API access or permission to reuse photos**. Facebook often requires cookies/authentication; this setup does **not** automate authentication, evade login barriers, or request credentials. If no media can be accessed, it returns `review_needed`. `--date-after` is *requested* for a 365-day cutoff; post dates may not be available in every extractor response and must be verified before publishing. Downloaded photos are always marked `rights_confirmed_for_preview: false` and `post_date_verified: false` until reviewed.

## Optional JS gallery scan and local HTML QA

```bash
pip install -r requirements-browser.txt
python -m playwright install chromium
python -m app.browser_gallery --project projects/example-groomer-com --url https://example-groomer.com/gallery
python -m app.local_preview --html projects/example-groomer-com/website/index.html
```

Browser gallery saves a *candidate list* from rendered content and attempts to download new candidates through the same bounded, robots-aware website downloader. Add `--no-download` if you only want the candidate list. Local preview creates screenshots at **1440/1024/768/390/360** and a machine-readable report. Create a small photo-contact sheet with `python -m app.contact_sheet --project projects/example-groomer-com`.

## Optional n8n + collector Docker

```bash
docker compose up --build -d
```

- n8n: http://localhost:5678
- collector: http://localhost:8787/docs
- Import `n8n/01-submit-asset-research.json` and `n8n/02-check-asset-job.json`.
- n8n workflow webhook: POST `http://localhost:5678/webhook/pet-grooming-research` with JSON body `{"url":"https://example-groomer.com"}` after activation.
- Get status: GET `http://localhost:5678/webhook/pet-grooming-research-status?jobId=...`.

## Safe storage cleanup (after final approval only)

Create these files **only after** the final design passes review:

- `delivery/approved-homepage.html` (final locally runnable source)
- `delivery/ghl-ready.html` (final paste-ready GHL snippet)
- `delivery/retained-assets.json` listing all approved locally referenced assets:

```json
{"approved": true, "assets": ["assets/website/real-logo.png", "assets/instagram/hero.jpg"]}
```

Then:

```bash
python -m app.cleanup --project projects/example-groomer-com --mode plan
python -m app.cleanup --project projects/example-groomer-com --mode archive
python -m app.cleanup --project projects/example-groomer-com --mode prune --confirm
```

