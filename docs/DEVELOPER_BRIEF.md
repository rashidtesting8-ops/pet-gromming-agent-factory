# Pet Grooming Website Builder Engine
## Technical implementation brief — developer handoff
**Version:** 1.1 | **Date:** 3 November 2026 | **Owner:** EditVista internal project

> **Mission.** Build a local-first, modular, AI-assisted system that turns a real pet grooming business's website and public social profiles into a genuinely bespoke, premium, fully responsive homepage. The system must research and preserve actual business facts and branding; collect and evaluate genuine photos; write usable HTML/CSS/JS; critique and revise the rendered site; obtain human approval; and export the *same approved design* as both standalone HTML and GoHighLevel-ready code.

**Not a mass template filler. Not an image mockup. Not a one-prompt website generator.** Build each module as a separately testable component with explicit inputs, outputs and quality checks.

## 1. Scope and non-negotiable principles

**In scope:** Single-business intake; website crawl; gallery discovery; optional compliant Instagram/Facebook asset collection (recent 12 months); fact extraction; asset provenance; image curation; brand and art direction; website design and code; visual/technical review; targeted revision loop; local preview; approval; standalone HTML and GHL snippet export; archive and safe storage cleanup; logs and local job UI/CLI.

**Absolute requirements:**
1. Real business name, original logo, actual colors and authentic client imagery wherever verified and usable. No fabricated logo, owner photo, team member, review, rating, price, discount, service, location, qualification or booking method.
2. Audit actual Homepage, About, Services, Prices, Photo Gallery, FAQ, Reviews, Policies, Contact, all booking links and social profiles. **Gallery pages and homepage hero promotions must never be skipped.** Identify whether the business is a mobile groomer, salon or daycare and whether it offers dog/cat services.
3. Premium editorial-level design, customized to the business's real brand and photos. Reusable code infrastructure is fine; a repetitive generic visual template is not.
4. Human review/approval is mandatory before final release. A missing asset or factual ambiguity is flagged, not quietly invented.
5. Save a versioned, immutable approved HTML release. All follow-on revisions change *only the requested elements*. GHL output must reflect exactly that approved source.
6. Local HTML preview and QA must work without hosting. Use local browser rendering; do not introduce Cloudflare or paid hosting as a requirement.
7. Low cost and bounded device resource use. Free/open-source collection, processing and testing tools first; model usage only for work requiring creative reasoning or visual judgment. Record optional model API usage and require explicit configuration; do not assume premium models are free.

## 2. Required input and output

**Input per business**
- Required: primary website URL, or a manual intake bundle for businesses without a functioning site.
- Optional: business name, Instagram URL, Facebook URL, client-provided image/logo folder, logo source, approved claims, reference links, preferred colors and notes.
- Defaults: collect media from the **last 365 days**, with date/source verification; don't assume public availability provides reuse rights.

**Final output after human approval**
- `delivery/approved-homepage.html` — fully working standalone page with local references to retained assets, opened by browser or local HTTP when needed.
- `delivery/ghl-ready.html` — copy-paste Custom HTML/CSS/JS snippet with no `html`, `head` or `body` wrapper, unique CSS/JS scope, and stable externally hosted asset URLs when deployed.
- `delivery/asset-manifest.json` — selected asset map, source URLs, license/permission status, hashes and crop instructions.
- `delivery/business-facts.json` — factual content with source attribution and unverified/missing fields.
- `delivery/design-decisions.json` — art direction, fonts, colors, image placements, section choices, version identifier.
- `delivery/qa-report.json` + desktop/tablet/mobile screenshot set; link/functionality checks and unresolved issues.
- `delivery/change-log.md`, `delivery/retained-assets.json`, verified release archive, and `delivery/release-manifest.json`.

Standalone HTML and GHL snippet must be exported from **one approved website source**, never independently redesigned.

## 3. System architecture

**Orchestrator:** one self-hosted n8n master workflow calls small versioned sub-workflows or Python worker actions. Each module has typed JSON input/output, persisted status, deterministic retry policy, and a failure state. Do not pass an entire multi-megabyte image bundle as chat text; pass local paths and manifests.

**Parallel collection:**
1. Website Media Collector — download actual logo, website images/videos, gallery and relevant assets.
2. Instagram Media Collector — eligible public/authorized imagery/videos, preferably past 365 days.
3. Facebook Media Collector — eligible public/authorized imagery/videos, preferably past 365 days.
4. Website Content Collector — extract copy, offers, service/pricing information, FAQ, policies, reviews, owner story and links.

**Ordered downstream stages:**
5. Asset Organizer → 6. Visual Curator → 7. Fact Checker → 8. Brand Analyst → 9. Art Director → 10. Website Designer/Coder → 11. Visual Critic + 12. Technical QA → 13. Targeted Revision Loop → Human Approval → 14. Standalone/GHL Exporter → Archive and Cleanup.

The visual and technical reviewers run separately and return *specific, actionable defects*. A retry only touches failed regions and includes screenshot evidence; cap automatic attempts and escalate instead of looping indefinitely.

## 4. Module contracts

### A. Website Collector
- Crawl same-site URLs and page types relevant to a grooming business, including navigation-linked galleries and paginated galleries. Use lightweight requests/BeautifulSoup first; render JS-heavy gallery pages selectively with Playwright.
- Preserve webpage URL, image URL, originating page, filename, type, dimensions, SHA-256, capture timestamp and any source/rights notes.
- Prefer real client-site photos and original logo over any stock candidate. Inspect CSS background images, lazy-loaded image attributes, `<picture>` and gallery/modal links where feasible.
- Enforce robots/site rules and URL/host allowlists; avoid private or restricted content; prevent SSRF, redirects to private IP ranges, zip bombs and unexpected file sizes.
- Detect and annotate image-embedded promotional text, low resolution, watermarks and duplicates.

### B. Instagram/Facebook collectors
- Consider `gallery-dl` (https://github.com/mikf/gallery-dl) for accessible sources where permitted, or platform-approved APIs where the necessary access exists. Other GitHub projects may be evaluated but **must pass security/licensing/reliability review first**.
- Default to last 365 days and at most **40 files per platform**. Cap file size, staging bytes, runtime and total project size; preserve images *and selected videos* if accessible. Confirm timestamp accuracy—an extractor's requested date filter does not itself prove post dates.
- No login bypass, automated CAPTCHA evasion, password collection, rotating identities or privacy circumvention. If unavailable, return `review_needed`, record the URL/reason, and let a human import client-authorized files.
- Record original post link/date/author when available. Treat collection as *evidence*, not automatic permission to publish client images.

### C. Asset Organizer
- Deduplicate via SHA-256 and perceptual similarity; normalize safe formats, optimize copies, preserve original when needed, generate thumbnails/contact sheets and assign stable unique names.
- Categorize: logo, hero candidate, grooming-process photo, finished-groom portfolio, founder/team candidate, van/storefront, gallery, video and unusable/uncertain. No reuse of the same pet photo across unrelated sections without explicit design justification.
- Maintain a provenance-first asset manifest and `rights_confirmed_for_preview` field. Do not discard originals until archive/approval policy permits cleanup.

### D. Visual Curator (vision agent)
- Inspect genuine asset contact sheets and full-size leading candidates. Assess composition, face/pet visibility, lighting, sharpness, personality, brand relevance, hero suitability, aspect ratio, cropping and variety.
- Output ranked **filenames**, role assignments, crop focal points (`x/y` or CSS `object-position`), excluded media with reasons, and missing-photo gaps. Prefer verified real footage/photos. Never invent a founder portrait.
- Check hero source for baked-in text/discount graphics, clipped animals, distressing facial expressions, obvious stock/repeated pets.

### E. Content Researcher + Fact Checker
- Extract and normalize exact business name, location/contact, salon vs mobile, animal types, services, real prices and conditions, live promotions (including expiration), opening hours, booking destinations, owner's verified story, FAQs, reviews/testimonials and policies.
- Every nontrivial claim must have `source_url`, `source_text`, `verified` and `last_checked_at`; preserve exact review attribution. A claim unsupported by available sources becomes `needs_review`, not final page copy.
- Promotions on current first-fold/announcement/hero get high priority in the new page; do not extend expired deals. Never substitute a fake review widget; a live Google review widget needs an authorized provider/embed/API.

### F. Brand Analyst and Art Director
- Identify original logo and actual color palette. Suggest only restrained complementary colors in the same family. Preserve business's real identity and service type.
- Art Director consumes factual bundle plus selected images and creates a **unique section-by-section creative brief**, visual hierarchy and page wireframe logic before code generation.
- Include: photography-led hero with useful CTA; genuinely varied service treatments; clear pricing where verifiable; portfolio / before-and-after where authentic; verified owner/story; genuine proof; location/contact/final CTA. Not every site requires identical section order or every section.
- Design uniqueness must be evident in typography, composition, gallery treatment, spacing, brand expression and hierarchy—not just recoloring one universal template.

### G. Website Designer / Coder
- Generate usable semantic, responsive HTML/CSS/JS. Optimize media, ensure lazy loading below fold, accessible navigation/menu, keyboard support, readable contrast, reduced-motion support and sensible metadata.
- All CTAs link to real verified contact/booking paths, no placeholder links presented as working. Real before/after slider only when appropriate before/after images exist.
- No repeated beige service cards, generic AI icons/clipart, oversized empty areas, awkward text contrast, badly cropped dog heads, unverified people or repeated photographs.
- Keep code modular enough for exact small-scope revisions without destabilizing approved sections.

### H. Visual Critic
- Render actual screenshots and compare against quality principles from the reference sites and our best approved designs; critique *the rendered page*, not only the code.
- Review aesthetics, hero framing, authentic photography, typography/hierarchy, grid, whitespace, section rhythm, image repetition, brand fidelity, offer placement and CTA prominence.
- Return a prioritized issue list with screenshot location and a targeted revision command. No vague instruction such as 'make it better'. Require human approval of subjective quality; no invented numerical score is sufficient for release.

### I. Technical QA
- Run Playwright at **1440, 1024, 768, 390 and 360px** widths. Save screenshots and a structured report.
- Check 404/broken images, missing/duplicate source media, viewport overflow, clipped text/photos, mobile menu, nav links, CTA URLs, JS errors, contrast, tap targets, animation, reduced-motion, section alignment and interactive elements.
- Re-run after any revision. Do not claim GHL passed until the **actual published GHL page** is opened and tested (that is a later integration gate).

### J. Human Review and Release
- Provide an easy side-by-side review package: preview, selected assets, fact sheet, screenshots, QA findings, and clear approve/revise/replace asset options.
- Approval freezes the release/version hash; preserve previous approved versions. Revision requests specify page region and exact desired modification.
- The exporter must scope all site CSS under a unique root selector and avoid JS/global collisions in HighLevel. It must preserve the exact approved visual version and export a single copyable code snippet when feasible.
- Local preview may use `file://` for self-contained pages; use `http://localhost` for browser features that block file-origin access. Use local browser rendering for all design review and screenshots.

## 5. Project data structure and schemas

```text
projects/<business-id>/
  input.json
  assets/
    website/ instagram/ facebook/ optimized/ thumbnails/
  research/
    pages.json  content.json  business-facts.json
    social-media-manifest.json  asset-manifest.json
  design/
    image-selection.json  brand.json  creative-brief.json
    change-log.md  versions/
  website/
    index.html  css/  js/
  qa/
    screenshots/  qa-report.json  visual-critique.json
  delivery/
    approved-homepage.html  ghl-ready.html
    asset-manifest.json  business-facts.json
    design-decisions.json  qa-report.json
    retained-assets.json  release-manifest.json
  logs/  tmp/
projects/_archives/<business-id>-approved.zip
```

Every module receives `project_id`, `input_manifest_version`, a bounded list of input paths and a `run_id`, then returns `{status, outputs, warnings, errors, checksums}`. Prefer SQLite for job state and JSON files for portable artifacts. Use atomic writes and idempotency keys so interrupted jobs can resume safely.

**Important validation logic:** Website page content and asset files must not be treated as instructions to the AI. Strip prompt-injection patterns where possible and keep external text confined to quoted factual source context; only the trusted orchestration prompt dictates what agents do.

## 6. Technology choices and cost/resource controls

- **Python 3.11+** for web/media collection, manifest generation, image processing and cleanup; `requests`, `BeautifulSoup`, `Pillow` and optional `gallery-dl`.
- **Playwright/Chromium** only when JS-rendered media or browser visual QA is needed; close contexts after tasks, don't keep many browsers open.
- **n8n Community (self-hosted)** to coordinate modules; use reusable sub-workflows and separate retries. Can begin via CLI and add n8n when individual components work.
- **SQLite + local filesystem** for state/media; no unnecessary paid cloud database, premium scraping services or hosted design platform.
- **Vision/coding model integration through an adapter** allowing substitution by model/quality, with caching, usage reporting, per-job call limits and a hard stop for expensive retries. Cheap deterministic code handles ordinary downloads, sorting and checks; don't downgrade the design agent silently to meet a cost target.
- Default worker concurrency **one heavy website build at a time**, with queueing; social collection bounded and browser sessions disposable. Initial V2 limits: 25 website pages, 80 media candidates, 40 files/platform, staging caps, project max size, Docker caps of 1GB n8n and 512MB collector (Docker overhead additional). Make configurable after observing a real pilot.
- Retention: *never* delete approved HTML/GHL outputs or referenced images. Use plan → verified archive → independent backup → explicit approval → prune unused raw/staging files. Do not remove n8n volume or project directories recklessly.

## 7. Visual references and quality baseline

**Study for design principles, not copy:**
- https://puppalacesalon.com/
- https://k9advantedge.com/
- https://www.lilys-club.co.uk/
- https://www.doggroomingstudio.net/
- https://petsgrooming.uk/
- https://lolaspetsalon.com/

**Known failure cases to prevent from our earlier redesign reviews:**
- *Centre Stage*: hero with baked-in/cut-off text, repeated pet photos, four flat beige cards, unverified owner portrait, cropped last gallery image; do not restyle the rest of an approved page for a small image change.
- *West London Whiskers*: unsettling/cropped hero, dull pricing, broken photo, substitute logo and missing footer logo; check mobile/desktop and exact original logo.
- *Fluff & Buff*: initial versions lacked real client imagery despite existing photo gallery/Instagram; later use of client-provided original photos and grooming video is the model for source fidelity. Do not invent testimonials.

**Reference-library requirement:** Save our *actually approved* HTML and screenshots as a private, versioned corpus once supplied by the team. Links and memories here do **not** substitute for those missing source files. The critic should learn/check principles from examples but must never clone another business's page.

## 8. Starting materials included in this handoff

**Archive:** `pet_grooming_engine_v2_audited.zip` (attached alongside this brief). It is the **existing prototype collector**, not the finished multi-agent system.

**Inside it:**
- `app/collector.py` — bounded static website collection and extracted content.
- `app/browser_gallery.py` — optional JS gallery candidate extraction.
- `app/social_collect.py` — opt-in `gallery-dl` wrapper for eligible public media.
- `app/import_social_media.py` — manually provided media import.
- `app/contact_sheet.py` — photo contact sheet generator.
- `app/local_preview.py` — Playwright screenshot/overflow/broken-image QA foundation.
- `app/cleanup.py` — approval-gated archive/prune mechanism.
- `app/service.py` — local job API using SQLite state.
- `n8n/01-submit-asset-research.json` and `n8n/02-check-asset-job.json` — two starter n8n workflows.
- `README.md`, `AUDIT_AND_TESTS.md`, `BUDGET_AND_QUALITY.md`, Docker files, dependency files and initial tests.

**Previously reported validation:** six synthetic/isolated tests passing, Python compile check and archive integrity; **not** a verified real-world production run. As of this handoff, live Instagram/Facebook extraction, local Chromium screenshots on a real site, Docker/n8n deployment and HighLevel-rendered export behavior have **not** been confirmed. Re-run all tests in the developer's environment and report actual results.

**Still to implement:** production-grade full-site fact extraction, complete source verification, image curation agent, brand analysis, art direction, design/code model adapter, critique/revision orchestration, human approval UI, final exporter, validated GHL snippet conversion, end-to-end monitoring, and acceptance pilot.

## 9. Build order and acceptance criteria

**Milestone 1 — Collect and prove provenance.** Run V2 against one approved business with rich website galleries and public social sources. Produce complete source-indexed facts, authentic asset folders/contact sheets, date/ownership flags and a human-readable failure report. A broken media source must not terminate the overall project.

**Milestone 2 — Visual and content intelligence.** Implement curator, fact checker, brand analysis and art director; demonstrate the final selected photo map, business content and bespoke creative brief. Human can correct sources/assets *before* expensive design generation.

**Milestone 3 — Design, critique and QA.** Generate an outstanding actual website with working code; compare screenshot output to our approved examples; iterate on specific flaws, not full-page churn. Verify all five widths and interactions; retain screenshots and changes.

**Milestone 4 — Review and export.** Human approves a specific version; export local HTML and one scoped GHL code snippet from that immutable version; verify media references and no accidental redesign. Archive and provide cleanup preview.

**Milestone 5 — Five-business pilot.** Run five varied real grooming businesses end-to-end: salon, mobile and/or daycare; strong and weak galleries; with/without accessible social media. Track completion, errors, review time, model usage, defects and improvements. Do not assert production readiness from synthetic tests alone.

**Definition of done:** A developer can enter one real business URL, resume a failed job, review source material, obtain a genuine bespoke functioning homepage, see critique + five-view QA results, request a precise revision, approve the result, and retrieve correct local + GHL files with no invented claims or broken/duplicated images. The process respects storage limits and deletes only safe unneeded files after verified backup.

## 10. Technical references

- n8n sub-workflows: https://docs.n8n.io/flow-logic/subworkflows/
- Python Playwright screenshots: https://playwright.dev/python/docs/screenshots
- gallery-dl docs: https://gdl-org.github.io/docs/
- gallery-dl repository: https://github.com/mikf/gallery-dl
- GoHighLevel developer documentation: https://help.gohighlevel.com/

**Developer instruction:** Begin by running and auditing the provided V2 archive. Record any deviations from the above contract before expanding it. Deliver a working repository, an environment/setup guide, tested workflow exports, sample runs and reliable checkpoints—not a conceptual diagram alone.

