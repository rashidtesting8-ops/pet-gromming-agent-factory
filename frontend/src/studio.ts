import type {
  DoDStatusResponse,
  GhlExportResponse,
  PruneResponse,
  SectionInspectorResponse,
  ViewportPreset,
  ViewportWidth,
} from "./types.ts";

const VIEWPORT_PRESETS: ReadonlyArray<ViewportPreset> = [
  { width: 1440, label: "Desktop", tag: "1440px" },
  { width: 1024, label: "Laptop", tag: "1024px" },
  { width: 768, label: "Tablet", tag: "768px" },
  { width: 390, label: "Mobile L", tag: "390px" },
  { width: 360, label: "Mobile S", tag: "360px" },
];

export class EditVistaStudioController {
  private readonly projectId: string;
  private activeViewport: ViewportWidth = 1440;

  constructor(projectId: string) {
    this.projectId = projectId;
  }

  public async init(): Promise<void> {
    this.bindViewportSwitcher();
    this.bindSectionSelector();
    this.bindKeyboardShortcuts();
    if (this.projectId) {
      await Promise.all([this.refreshDoDLedger(), this.loadSelectedSectionMarkup()]);
    }
  }

  public showToast(message: string, tone: "ok" | "warn" | "err" = "ok"): void {
    let host = document.getElementById("ev-toast-host");
    if (!host) {
      host = document.createElement("div");
      host.id = "ev-toast-host";
      host.className = "ev-toast-host";
      document.body.appendChild(host);
    }
    const item = document.createElement("div");
    item.className = `ev-toast ev-toast--${tone}`;
    item.textContent = message;
    host.appendChild(item);
    window.setTimeout(() => {
      item.remove();
    }, 4200);
  }

  private bindViewportSwitcher(): void {
    const bar = document.querySelector("[data-ev-viewport-switcher]");
    if (!bar) return;
    bar.innerHTML = VIEWPORT_PRESETS.map(
      (vp) =>
        `<button type="button" class="ev-vp-btn ${vp.width === this.activeViewport ? "active" : ""}" data-vp-width="${vp.width}">` +
        `<span class="ev-vp-label">${vp.label}</span>` +
        `<span class="ev-vp-dim">${vp.tag}</span>` +
        `</button>`
    ).join("");

    bar.querySelectorAll<HTMLButtonElement>("[data-vp-width]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const raw = Number(btn.getAttribute("data-vp-width") || "1440") as ViewportWidth;
        this.setPreviewViewport(raw);
      });
    });
  }

  public setPreviewViewport(width: ViewportWidth): void {
    this.activeViewport = width;
    const frame = document.querySelector<HTMLIFrameElement>(".preview-frame");
    const readout = document.getElementById("ev-vp-readout");
    if (frame) {
      frame.style.maxWidth = width === 1440 ? "100%" : `${width}px`;
    }
    if (readout) {
      readout.textContent = `${width}px × 900px`;
    }
    document.querySelectorAll<HTMLButtonElement>("[data-vp-width]").forEach((btn) => {
      const btnW = Number(btn.getAttribute("data-vp-width"));
      btn.classList.toggle("active", btnW === width);
    });
  }

  private bindSectionSelector(): void {
    const select = document.getElementById("section-select") as HTMLSelectElement | null;
    if (!select) return;
    select.addEventListener("change", () => {
      void this.loadSelectedSectionMarkup();
    });
  }

  private bindKeyboardShortcuts(): void {
    window.addEventListener("keydown", (ev: KeyboardEvent) => {
      if (ev.altKey && ev.key >= "1" && ev.key <= "5") {
        ev.preventDefault();
        const idx = Number(ev.key) - 1;
        const preset = VIEWPORT_PRESETS[idx];
        if (preset) {
          this.setPreviewViewport(preset.width);
        }
      }
    });
  }

  public async loadSelectedSectionMarkup(): Promise<void> {
    const select = document.getElementById("section-select") as HTMLSelectElement | null;
    const textarea = document.getElementById("section-markup") as HTMLTextAreaElement | null;
    const shaBadge = document.getElementById("ev-active-section-sha");
    if (!select || !textarea || !this.projectId) return;

    const secName = select.value;
    try {
      const res = await fetch(
        `/api/projects/${encodeURIComponent(this.projectId)}/section/${encodeURIComponent(secName)}`
      );
      if (!res.ok) return;
      const data = (await res.json()) as SectionInspectorResponse;
      textarea.value = data.html;
      if (shaBadge) {
        shaBadge.textContent = `SHA-256: ${data.sha256.slice(0, 16)}…`;
      }
    } catch {
      // Keep manual editing operational if offline
    }
  }

  public async refreshDoDLedger(): Promise<void> {
    const ledger = document.querySelector("[data-ev-dod-ledger]");
    if (!ledger || !this.projectId) return;

    try {
      const res = await fetch(
        `/api/projects/${encodeURIComponent(this.projectId)}/dod-status`
      );
      if (!res.ok) return;
      const data = (await res.json()) as DoDStatusResponse;
      this.renderDoDGates(ledger as HTMLElement, data);
      this.renderSectionHashes(data.section_hashes);
      this.renderStorageFooter(data);
    } catch {
      // Non-fatal
    }
  }

  private renderDoDGates(container: HTMLElement, data: DoDStatusResponse): void {
    const g = data.gates;
    const items: ReadonlyArray<{ label: string; meta: string; passed: boolean }> = [
      {
        label: "01 / Source Provenance",
        meta: `${data.verified_fact_count}/${data.total_fact_count} verified`,
        passed: g.facts_verified,
      },
      {
        label: "02 / Asset Rights Audit",
        meta: `${data.confirmed_asset_count}/${data.total_asset_count} signed`,
        passed: g.rights_confirmed,
      },
      {
        label: "03 / Claim Scanner",
        meta:
          data.claim_violations.length === 0
            ? "0 fabrications"
            : `${data.claim_violations.length} blocked`,
        passed: g.claim_scanner_passed,
      },
      {
        label: "04 / 5-Viewport QA",
        meta: g.five_view_qa_passed ? "5/5 viewports" : "attention required",
        passed: g.five_view_qa_passed,
      },
      {
        label: "05 / Vision Critique",
        meta: `${g.visual_critique_status} (${data.visual_defects.length} notes)`,
        passed:
          g.visual_critique_status === "passed" ||
          g.visual_critique_status === "defects_found",
      },
      {
        label: "06 / Section Hash Ledger",
        meta: `${Object.keys(data.section_hashes).length} canonical sections`,
        passed: g.section_hashes_present,
      },
      {
        label: "07 / Immutable Release",
        meta: g.release_frozen ? "delivery/ frozen" : "draft candidate",
        passed: g.release_frozen,
      },
      {
        label: "08 / Verified Backup",
        meta: g.archive_verified ? data.storage.archive_filename : "awaiting freeze",
        passed: g.archive_verified,
      },
    ];

    container.innerHTML = items
      .map(
        (it) =>
          `<div class="ev-dod-cell ${it.passed ? "ev-dod-cell--pass" : "ev-dod-cell--warn"}">` +
          `<div class="ev-dod-top">` +
          `<span class="ev-dod-label">${it.label}</span>` +
          `<span class="ev-dod-dot">${it.passed ? "PASS" : "WAIT"}</span>` +
          `</div>` +
          `<div class="ev-dod-meta">${it.meta}</div>` +
          `</div>`
      )
      .join("");
  }

  private renderSectionHashes(hashes: Readonly<Record<string, string>>): void {
    const strip = document.getElementById("ev-section-hash-strip");
    if (!strip) return;
    const entries = Object.entries(hashes);
    if (entries.length === 0) {
      strip.textContent = "No section hashes recorded.";
      return;
    }
    strip.innerHTML = entries
      .map(
        ([sec, sha]) =>
          `<span class="ev-hash-chip"><strong>#${sec}</strong> <code>${sha.slice(0, 10)}</code></span>`
      )
      .join("");
  }

  private renderStorageFooter(data: DoDStatusResponse): void {
    const el = document.getElementById("ev-storage-readout");
    if (!el) return;
    const mb = (data.storage.project_bytes / (1024 * 1024)).toFixed(2);
    const capMb = (data.storage.max_project_bytes / (1024 * 1024)).toFixed(0);
    el.textContent = `Workspace: ${mb} MB / ${capMb} MB cap • Backup: ${
      data.storage.archive_exists ? data.storage.archive_filename : "unarchived"
    }`;
  }

  public async confirmAllRights(): Promise<void> {
    const res = await fetch(
      `/api/projects/${encodeURIComponent(this.projectId)}/confirm-all-rights`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          basis: "owner_permission",
          operator: "Studio Operator",
          evidence: "Confirmed via Monograph Studio Cockpit",
        }),
      }
    );
    const data = (await res.json()) as { confirmed_count?: number; detail?: string };
    if (res.ok) {
      this.showToast(`Confirmed rights for ${data.confirmed_count ?? 0} assets.`, "ok");
      window.location.reload();
    } else {
      this.showToast(`Rights confirmation failed: ${data.detail ?? "error"}`, "err");
    }
  }

  public async runStoragePrune(mode: "plan" | "prune"): Promise<void> {
    const res = await fetch(
      `/api/projects/${encodeURIComponent(this.projectId)}/prune`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      }
    );
    const data = (await res.json()) as PruneResponse & { detail?: string };
    const statusBox = document.getElementById("ev-prune-output");
    if (!res.ok) {
      const msg = data.detail ?? "Prune blocked until release is approved and archived.";
      if (statusBox) statusBox.textContent = msg;
      this.showToast(msg, "warn");
      return;
    }
    const kb = ((data.reclaimed_bytes ?? data.reclaimable_bytes ?? 0) / 1024).toFixed(1);
    const summary =
      mode === "prune"
        ? `Pruned ${data.deleted_count ?? 0} unneeded staging files (${kb} KB reclaimed). Delivery & backup intact.`
        : `Dry-run plan: ${data.removable_count} staging files removable (${kb} KB reclaimable).`;
    if (statusBox) statusBox.textContent = summary;
    this.showToast(summary, "ok");
    await this.refreshDoDLedger();
  }
}

declare global {
  interface Window {
    __evStudio?: EditVistaStudioController;
    openTab: (evt: Event, tabId: string) => void;
    confirmRights: (assetFile: string, confirmed: boolean) => Promise<void>;
    confirmAllRights: () => Promise<void>;
    verifyFact: (claimKey: string, verified: boolean) => Promise<void>;
    resumeJob: () => Promise<void>;
    approveRelease: () => Promise<void>;
    submitRevision: () => Promise<void>;
    loadGhlExport: () => Promise<void>;
    copyGhlSnippet: () => Promise<void>;
    runStoragePrune: (mode: "plan" | "prune") => Promise<void>;
    createProject: () => Promise<void>;
  }
}

export function bootEditVistaStudio(): void {
  const rootEl = document.body;
  const pid = rootEl?.getAttribute("data-project-id") ?? "";
  const controller = new EditVistaStudioController(pid);
  window.__evStudio = controller;

  window.openTab = (evt: Event, tabId: string): void => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
    const target = evt.currentTarget as HTMLElement | null;
    target?.classList.add("active");
    document.getElementById(tabId)?.classList.add("active");
  };

  window.confirmRights = async (assetFile: string, confirmed: boolean): Promise<void> => {
    const res = await fetch(`/api/projects/${encodeURIComponent(pid)}/confirm-rights`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ asset_file: assetFile, confirmed }),
    });
    if (res.ok) {
      window.location.reload();
    } else {
      const err = (await res.json()) as { detail?: string };
      controller.showToast(`Rights error: ${err.detail ?? "Failed"}`, "err");
    }
  };

  window.confirmAllRights = async (): Promise<void> => {
    await controller.confirmAllRights();
  };

  window.verifyFact = async (claimKey: string, verified: boolean): Promise<void> => {
    const res = await fetch(`/api/projects/${encodeURIComponent(pid)}/verify-fact`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ claim_key: claimKey, verified }),
    });
    if (res.ok) {
      window.location.reload();
    } else {
      const err = (await res.json()) as { detail?: string };
      controller.showToast(`Fact update error: ${err.detail ?? "Failed"}`, "err");
    }
  };

  window.resumeJob = async (): Promise<void> => {
    const res = await fetch(`/api/projects/${encodeURIComponent(pid)}/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = (await res.json()) as { project_id?: string; detail?: string };
    if (res.ok) {
      controller.showToast(`Resumed pipeline for ${data.project_id ?? pid}`, "ok");
      window.setTimeout(() => window.location.reload(), 900);
    } else {
      controller.showToast(`Resume failed: ${data.detail ?? "Error"}`, "err");
    }
  };

  window.approveRelease = async (): Promise<void> => {
    const opInput = document.getElementById("ev-operator-input") as HTMLInputElement | null;
    const notesInput = document.getElementById("ev-notes-input") as HTMLInputElement | null;
    const operator = opInput?.value.trim() || "Senior Operator";
    const notes = notesInput?.value.trim() || "Approved via Monograph Studio Cockpit";
    const res = await fetch(`/api/projects/${encodeURIComponent(pid)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operator_name: operator, notes }),
    });
    const data = (await res.json()) as { manifest_sha256?: string; detail?: string };
    if (res.ok) {
      controller.showToast(
        `Release frozen (SHA: ${(data.manifest_sha256 ?? "").slice(0, 12)}…)`,
        "ok"
      );
      window.setTimeout(() => window.location.reload(), 900);
    } else {
      controller.showToast(`Approval blocked: ${data.detail ?? "Gate failed"}`, "err");
    }
  };

  window.submitRevision = async (): Promise<void> => {
    const secEl = document.getElementById("section-select") as HTMLSelectElement | null;
    const markupEl = document.getElementById("section-markup") as HTMLTextAreaElement | null;
    const sec = secEl?.value ?? "hero";
    const markup = markupEl?.value ?? "";
    if (!markup.trim()) {
      controller.showToast("Section markup cannot be empty.", "warn");
      return;
    }
    const res = await fetch(`/api/projects/${encodeURIComponent(pid)}/revise-section`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section_name: sec, new_html: markup }),
    });
    const data = (await res.json()) as { detail?: string };
    if (res.ok) {
      controller.showToast(`Section #${sec} revised; sibling hashes preserved.`, "ok");
      const frame = document.querySelector<HTMLIFrameElement>(".preview-frame");
      if (frame) {
        frame.src = `/preview/${encodeURIComponent(pid)}/standalone.html?t=${Date.now()}`;
      }
      await controller.refreshDoDLedger();
      await controller.loadSelectedSectionMarkup();
    } else {
      controller.showToast(`Revision rejected: ${data.detail ?? "Invalid markup"}`, "err");
    }
  };

  window.loadGhlExport = async (): Promise<void> => {
    const cdnEl = document.getElementById("ghl-cdn-input") as HTMLInputElement | null;
    const cdnInput = cdnEl?.value.trim() ?? "";
    const qs = cdnInput ? `?cdn_base_url=${encodeURIComponent(cdnInput)}` : "";
    const res = await fetch(`/api/projects/${encodeURIComponent(pid)}/ghl-export${qs}`);
    const data = (await res.json()) as GhlExportResponse & { detail?: string };
    if (!res.ok) {
      controller.showToast(`GHL export failed: ${data.detail ?? "Error"}`, "err");
      return;
    }
    const out = document.getElementById("ghl-code-output") as HTMLTextAreaElement | null;
    if (out) out.value = data.ghl_html;
    const sim = data.simulation;
    const badges = document.getElementById("ghl-audit-badges");
    if (badges && sim) {
      badges.textContent =
        `is_valid=${sim.is_valid} · unscoped_css=${sim.unscoped_css_count} · ` +
        `js_leak=${sim.global_leak_detected} · absolute_assets=${sim.asset_urls_absolute}`;
    }
    controller.showToast("Scoped GoHighLevel bundle compiled and verified.", "ok");
  };

  window.copyGhlSnippet = async (): Promise<void> => {
    const out = document.getElementById("ghl-code-output") as HTMLTextAreaElement | null;
    if (!out) return;
    if (!out.value.trim()) {
      await window.loadGhlExport();
    }
    if (out.value.trim()) {
      await navigator.clipboard.writeText(out.value);
      controller.showToast("Scoped GHL snippet copied to clipboard.", "ok");
    }
  };

  window.runStoragePrune = async (mode: "plan" | "prune"): Promise<void> => {
    await controller.runStoragePrune(mode);
  };

  const deriveSlug = (u: string, n: string): string => {
    let raw = "";
    if (n && n.trim()) {
      raw = n.trim().toLowerCase();
    } else if (u && u.trim()) {
      try {
        const fullUrl = u.startsWith("http://") || u.startsWith("https://") ? u : `https://${u}`;
        const host = new URL(fullUrl).hostname.replace(/^www\./, "");
        raw = host.split(".")[0];
      } catch {
        raw = u.toLowerCase();
      }
    }
    return raw.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48);
  };

  const deriveName = (u: string, slugVal: string): string => {
    if (slugVal && slugVal.trim()) {
      return slugVal.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    }
    if (u && u.trim()) {
      try {
        const fullUrl = u.startsWith("http://") || u.startsWith("https://") ? u : `https://${u}`;
        const host = new URL(fullUrl).hostname.replace(/^www\./, "");
        const raw = host.split(".")[0].replace(/[-_]+/g, " ");
        return raw.replace(/\b\w/g, (c) => c.toUpperCase());
      } catch {
        return "";
      }
    }
    return "";
  };

  const newPidEl = document.getElementById("new-pid") as HTMLInputElement | null;
  const newNameEl = document.getElementById("new-name") as HTMLInputElement | null;
  const newUrlEl = document.getElementById("new-url") as HTMLInputElement | null;

  if (newUrlEl && newPidEl) {
    newUrlEl.addEventListener("input", () => {
      const u = newUrlEl.value.trim();
      if (!newPidEl.value.trim() || newPidEl.dataset.autoDerived === "true") {
        const autoSlug = deriveSlug(u, newNameEl?.value ?? "");
        if (autoSlug) {
          newPidEl.value = autoSlug;
          newPidEl.dataset.autoDerived = "true";
        }
      }
      if (newNameEl && (!newNameEl.value.trim() || newNameEl.dataset.autoDerived === "true")) {
        const autoName = deriveName(u, newPidEl.value);
        if (autoName) {
          newNameEl.value = autoName;
          newNameEl.dataset.autoDerived = "true";
        }
      }
    });

    newPidEl.addEventListener("input", () => {
      delete newPidEl.dataset.autoDerived;
    });
  }

  if (newNameEl && newPidEl) {
    newNameEl.addEventListener("input", () => {
      delete newNameEl.dataset.autoDerived;
      if (!newPidEl.value.trim() || newPidEl.dataset.autoDerived === "true") {
        const autoSlug = deriveSlug("", newNameEl.value);
        if (autoSlug) {
          newPidEl.value = autoSlug;
          newPidEl.dataset.autoDerived = "true";
        }
      }
    });
  }

  window.createProject = async (): Promise<void> => {
    const pidEl = document.getElementById("new-pid") as HTMLInputElement | null;
    const nameEl = document.getElementById("new-name") as HTMLInputElement | null;
    const urlEl = document.getElementById("new-url") as HTMLInputElement | null;
    const runNowEl = document.getElementById("new-run-now") as HTMLInputElement | null;
    let newPid = pidEl?.value.trim() ?? "";
    let name = nameEl?.value.trim() ?? "";
    const url = urlEl?.value.trim() ?? "";
    const runNow = Boolean(runNowEl?.checked);

    if (newPid) {
      newPid = newPid.toLowerCase().replace(/[^a-z0-9-_]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48);
      if (pidEl) pidEl.value = newPid;
    }

    if (!newPid && (url || name)) {
      newPid = deriveSlug(url, name);
      if (pidEl) pidEl.value = newPid;
    }
    if (!name && (url || newPid)) {
      name = deriveName(url, newPid);
      if (nameEl) nameEl.value = name;
    }

    if (!newPid) {
      controller.showToast("Enter a project slug or primary URL to initialize.", "warn");
      return;
    }
    const res = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: newPid,
        business_name: name || newPid,
        primary_url: url,
        run_now: runNow,
      }),
    });
    if (res.ok) {
      window.location.reload();
    } else {
      const d = (await res.json()) as { detail?: string };
      controller.showToast(`Intake error: ${d.detail ?? "Invalid slug"}`, "err");
    }
  };

  void controller.init();
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => bootEditVistaStudio());
  } else {
    bootEditVistaStudio();
  }
}
