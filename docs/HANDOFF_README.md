# Developer handoff package — Pet Grooming Website Builder Engine

Read `DEVELOPER_BRIEF.pdf` for the full scope; `DEVELOPER_BRIEF.docx` and `DEVELOPER_BRIEF.md` are editable versions.

## Package contents
- `DEVELOPER_BRIEF.pdf`: implementation specification and quality standard.
- `DEVELOPER_BRIEF.docx`: editable specification.
- `DEVELOPER_BRIEF.md`: source Markdown specification.
- `pet_grooming_engine_v2_audited.zip`: existing local collector prototype (app code, two n8n workflow exports, docs, tests, Docker configuration). It is not a finished website builder.
- `BUSINESS_INPUT_EXAMPLE.json`: suggested per-business input structure with placeholders, **not real business data**.

## Start here
1. Extract and inspect `pet_grooming_engine_v2_audited.zip`.
2. Read its internal `README.md` and `AUDIT_AND_TESTS.md` before running anything.
3. Run the included tests and one real business website crawl on the developer's own machine; record the outcomes.
4. Build in the milestone order listed in the main brief. Do not start by writing a single giant end-to-end agent prompt.
5. Record and preserve source URLs, real branding, asset provenance, approved release hashes, targeted changes and five-width screenshots.

## What we do NOT have in this package
- No original client images or logos from earlier redesigns are included; they must be imported from lawful/verified sources or supplied by the team.
- No previously approved client HTML/screenshots are included; ask the design team for these to form the internal reference library.
- No completed AI image-curation agent, art-direction agent, website designer, visual critic, GHL exporter, human approval application or end-to-end live test is included.
- No API credentials or authorized social network access are included. Never request or store client passwords for scraping.

## Expected working end state
One business input -> source-authenticated facts/media -> reviewed asset map -> bespoke responsive coded website -> screenshot-backed critique/revision -> human approval -> exact standalone HTML plus GHL-ready snippet -> safe backup and optional cleanup.

