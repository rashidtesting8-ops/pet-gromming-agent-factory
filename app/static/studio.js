/* Generated from frontend/src/types.ts + frontend/src/studio.ts — DO NOT EDIT DIRECTLY */
(function () {
"use strict";
/**
 * Strict TypeScript domain contracts for the EditVista Monograph Studio Cockpit.
 */

                                                          

                                 
                                
                         
                       
 

                           
                                   
                                     
                                         
                                        
                                          
                                           
                                   
                                     
 

                                 
                                 
                                     
                                   
                                    
 

                                    
                              
                          
                           
                                       
                                    
                                         
                                     
                                                   
                                                            
                                   
                                                                 
 

                                           
                              
                                
                        
                          
 

                                      
                             
                                       
                                      
                                         
                                        
 

                                    
                              
                           
                                
                                
                            
                                           
 

                                
                        
                                   
                                     
                                  
                                  
                                    
                            
                                  
                         
 

                                                                                                  

                                    
                        
                          
                         
                               
                                 
                            
                                       
                            
 

                                        
                              
                                 
                               
                                  
                                                    
 



                               
                        
                              
                              
                           
                           
 

const BLUEPRINT_STAGES                                     = [
  {
    step: 1,
    shortLabel: "01 Intake",
    plainTitle: "Address & Security Check",
    analogy: "Checks that the business website is genuine and public, then creates an isolated build workspace.",
    pdfSpec: "PDF §1 · Anti-SSRF & URL Intake",
  },
  {
    step: 2,
    shortLabel: "02 Crawl",
    plainTitle: "Salon Walk-Through & Real Photos",
    analogy: "Reads About, Services, Prices, Reviews & Gallery (up to 25 pages) and downloads real dog photos.",
    pdfSpec: "PDF §2 · Max 25 Pages / 80 Media",
  },
  {
    step: 3,
    shortLabel: "03 Audit",
    plainTitle: "Strict Fact Check (Zero Fabrication)",
    analogy: "Saves phone, hours & real prices with exact website quotes—never invents fake prices or claims.",
    pdfSpec: "PDF §3 · Source Provenance Lock",
  },
  {
    step: 4,
    shortLabel: "04 Curate",
    plainTitle: "Best Dog Portraits Selected",
    analogy: "Removes blurry or duplicate images, seals SHA-256 hashes, and frames faces cleanly for mobile.",
    pdfSpec: "PDF §4 · SHA-256 & Rights Matrix",
  },
  {
    step: 5,
    shortLabel: "05 Brand",
    plainTitle: "Bespoke Luxury Colors & Fonts",
    analogy: "Extracts official brand palette from the salon logo and pairs Swiss editorial typography.",
    pdfSpec: "PDF §5 · Brand Art Direction",
  },
  {
    step: 6,
    shortLabel: "06 Build",
    plainTitle: "Custom Homepage Built From Scratch",
    analogy: "Generates semantic HTML5, responsive CSS, booking buttons, WhatsApp links & interactive map.",
    pdfSpec: "PDF §6 · Zero Generic Templates",
  },
  {
    step: 7,
    shortLabel: "07 Critic",
    plainTitle: "AI Design Inspector Review",
    analogy: "Visually audits typography contrast, layout rhythm, and card balance before browser testing.",
    pdfSpec: "PDF §7 · Multi-Modal Vision Critic",
  },
  {
    step: 8,
    shortLabel: "08 QA",
    plainTitle: "Tested on 5 Real Screen Sizes",
    analogy: "Opens real Chromium across Desktop (1440px), Laptop, Tablet, iPhone & Android (360px) with 0 errors.",
    pdfSpec: "PDF §8 · 5-Viewport Playwright QA",
  },
  {
    step: 9,
    shortLabel: "09 Sign-Off",
    plainTitle: "Manager Approval & Verified Backup",
    analogy: "Human manager reviews evidence, approves & locks delivery files, then verifies tarball backup.",
    pdfSpec: "PDF §9 · Human Gate & Safe Prune",
  },
];

const VIEWPORT_PRESETS                                = [
  { width: 1440, label: "Desktop", tag: "1440px" },
  { width: 1024, label: "Laptop", tag: "1024px" },
  { width: 768, label: "Tablet", tag: "768px" },
  { width: 390, label: "Mobile L", tag: "390px" },
  { width: 360, label: "Mobile S", tag: "360px" },
];

class EditVistaStudioController {
                   projectId        ;
          activeViewport                = 1440;
          activeBlueprintStep = 1;
          stagePollTimer                = null;
          monitorStartMs = 0;

  constructor(projectId        ) {
    this.projectId = projectId;
  }

         async init()                {
    this.renderBlueprintBar();
    this.bindViewportSwitcher();
    this.bindSectionSelector();
    this.bindKeyboardShortcuts();
    if (this.projectId) {
      await Promise.all([this.refreshDoDLedger(), this.loadSelectedSectionMarkup()]);
    }
  }

         showToast(message        , tone                        = "ok")       {
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

          bindViewportSwitcher()       {
    const bar = document.querySelector("[data-ev-viewport-switcher]");
    if (!bar) return;
    bar.innerHTML = VIEWPORT_PRESETS.map(
      (vp) =>
        `<button type="button" class="ev-vp-btn ${vp.width === this.activeViewport ? "active" : ""}" data-vp-width="${vp.width}">` +
        `<span class="ev-vp-label">${vp.label}</span>` +
        `<span class="ev-vp-dim">${vp.tag}</span>` +
        `</button>`
    ).join("");

    bar.querySelectorAll                   ("[data-vp-width]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const raw = Number(btn.getAttribute("data-vp-width") || "1440")                 ;
        this.setPreviewViewport(raw);
      });
    });
  }

         setPreviewViewport(width               )       {
    this.activeViewport = width;
    const frame = document.querySelector                   (".preview-frame");
    const readout = document.getElementById("ev-vp-readout");
    if (frame) {
      frame.style.maxWidth = width === 1440 ? "100%" : `${width}px`;
    }
    if (readout) {
      readout.textContent = `${width}px × 900px`;
    }
    document.querySelectorAll                   ("[data-vp-width]").forEach((btn) => {
      const btnW = Number(btn.getAttribute("data-vp-width"));
      btn.classList.toggle("active", btnW === width);
    });
  }

          bindSectionSelector()       {
    const select = document.getElementById("section-select")                            ;
    if (!select) return;
    select.addEventListener("change", () => {
      void this.loadSelectedSectionMarkup();
    });
  }

          bindKeyboardShortcuts()       {
    window.addEventListener("keydown", (ev               ) => {
      if (ev.key === "Escape") {
        this.closeStageMonitor();
      }
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

         async loadSelectedSectionMarkup()                {
    const select = document.getElementById("section-select")                            ;
    const textarea = document.getElementById("section-markup")                              ;
    const shaBadge = document.getElementById("ev-active-section-sha");
    if (!select || !textarea || !this.projectId) return;

    const secName = select.value;
    try {
      const res = await fetch(
        `/api/projects/${encodeURIComponent(this.projectId)}/section/${encodeURIComponent(secName)}`
      );
      if (!res.ok) return;
      const data = (await res.json())                            ;
      textarea.value = data.html;
      if (shaBadge) {
        shaBadge.textContent = `SHA-256: ${data.sha256.slice(0, 16)}…`;
      }
    } catch {
      // Keep manual editing operational if offline
    }
  }

         async refreshDoDLedger()                {
    const ledger = document.querySelector("[data-ev-dod-ledger]");
    if (!ledger || !this.projectId) return;

    try {
      const res = await fetch(
        `/api/projects/${encodeURIComponent(this.projectId)}/dod-status`
      );
      if (!res.ok) return;
      const data = (await res.json())                     ;
      this.renderDoDGates(ledger               , data);
      this.renderSectionHashes(data.section_hashes);
      this.renderStorageFooter(data);
    } catch {
      // Non-fatal
    }
  }

          renderDoDGates(container             , data                   )       {
    const g = data.gates;
    const items                                                                  = [
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

          renderSectionHashes(hashes                                  )       {
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

          renderStorageFooter(data                   )       {
    const el = document.getElementById("ev-storage-readout");
    if (el) {
      const mb = (data.storage.project_bytes / (1024 * 1024)).toFixed(2);
      const capMb = (data.storage.max_project_bytes / (1024 * 1024)).toFixed(0);
      el.textContent = `Workspace: ${mb} MB / ${capMb} MB cap • Backup: ${
        data.storage.archive_exists ? data.storage.archive_filename : "unarchived"
      }`;
    }
    const pruneBtn = document.getElementById("ev-btn-safe-prune")                            ;
    if (pruneBtn) {
      const unlocked = Boolean(data.gates.release_frozen && data.gates.archive_verified);
      pruneBtn.disabled = !unlocked;
      pruneBtn.title = unlocked
        ? "Archive verified — safe to prune unneeded staging files"
        : "Locked until Approve & Freeze Release creates a verified backup archive";
    }
  }

         async confirmAllRights()                {
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
    const data = (await res.json())                                                 ;
    if (res.ok) {
      this.showToast(`Confirmed rights for ${data.confirmed_count ?? 0} assets.`, "ok");
      window.location.reload();
    } else {
      this.showToast(`Rights confirmation failed: ${data.detail ?? "error"}`, "err");
    }
  }

         async runStoragePrune(mode                  )                {
    const res = await fetch(
      `/api/projects/${encodeURIComponent(this.projectId)}/prune`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      }
    );
    const data = (await res.json())                                       ;
    const statusBox = document.getElementById("ev-prune-output");
    if (!res.ok) {
      const msg = data.detail ?? "Prune blocked until release is approved and archived.";
      if (statusBox) statusBox.textContent = msg;
      this.showToast(msg, "warn");
      return;
    }
    const mb = ((data.reclaimed_bytes ?? data.reclaimable_bytes ?? 0) / (1024 * 1024)).toFixed(2);
    const kb = ((data.reclaimed_bytes ?? data.reclaimable_bytes ?? 0) / 1024).toFixed(1);
    let summary        ;
    if (mode === "prune") {
      const deleted = data.deleted_count ?? data.deleted_files ?? 0;
      summary = `Pruned ${deleted} unneeded staging files (${kb} KB reclaimed). Delivery & backup intact.`;
    } else if (data.pre_approval) {
      summary = `${data.removable_count} draft asset files (${mb} MB). ${data.note ?? ""}`;
    } else {
      summary = `Dry-run plan: ${data.removable_count} staging files removable (${kb} KB reclaimable).`;
    }
    if (statusBox) statusBox.textContent = summary;
    this.showToast(summary, data.pre_approval ? "warn" : "ok");
    await this.refreshDoDLedger();
  }

          escapeHtml(raw        )         {
    return raw
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

         renderBlueprintBar()       {
    const bar = document.querySelector("[data-ev-blueprint-bar]");
    if (!bar) return;
    bar.innerHTML = BLUEPRINT_STAGES.map(
      (s) =>
        `<button type="button" class="ev-bp-step ${s.step === this.activeBlueprintStep ? "active" : ""}" ` +
        `data-bp-step="${s.step}" onclick="focusBlueprintStage(${s.step})">` +
        `${this.escapeHtml(s.shortLabel)}` +
        `</button>`
    ).join("");
    this.focusBlueprintStage(this.activeBlueprintStep);
  }

         focusBlueprintStage(step        )       {
    this.activeBlueprintStep = step;
    const item = BLUEPRINT_STAGES.find((s) => s.step === step) ?? BLUEPRINT_STAGES[0];
    document.querySelectorAll                   ("[data-bp-step]").forEach((btn) => {
      btn.classList.toggle("active", Number(btn.getAttribute("data-bp-step")) === step);
    });
    const spot = document.getElementById("ev-blueprint-spotlight");
    if (spot && item) {
      spot.innerHTML =
        `<div class="ev-bp-spot-left">` +
        `<span class="ev-bp-spot-num">STAGE 0${item.step} OF 09</span>` +
        `<strong>${this.escapeHtml(item.plainTitle)}</strong>` +
        `<p>${this.escapeHtml(item.analogy)}</p>` +
        `</div>` +
        `<span class="ev-bp-spot-spec">${this.escapeHtml(item.pdfSpec)}</span>`;
    }
  }

         togglePipelineGuide()       {
    const drawer = document.querySelector("[data-ev-pipeline-guide]")                      ;
    if (!drawer) return;
    const nextOpen = drawer.hasAttribute("hidden");
    if (nextOpen) {
      drawer.removeAttribute("hidden");
    } else {
      drawer.setAttribute("hidden", "true");
    }
    document.querySelectorAll                   ("[data-ev-guide-toggle]").forEach((btn) => {
      btn.classList.toggle("active", nextOpen);
    });
  }

         async openStageMonitor(targetPid        , autoPoll = false)                {
    const modal = document.querySelector("[data-ev-live-stepper]")                      ;
    if (!modal || !targetPid) return;
    this.stopStagePoll();
    this.monitorStartMs = Date.now();
    modal.removeAttribute("hidden");
    await this.refreshStageMonitor(targetPid, autoPoll);
    if (autoPoll) {
      this.stagePollTimer = window.setInterval(() => {
        void this.refreshStageMonitor(targetPid, true);
      }, 1200);
    }
  }

         closeStageMonitor()       {
    this.stopStagePoll();
    const modal = document.querySelector("[data-ev-live-stepper]")                      ;
    modal?.setAttribute("hidden", "true");
  }

          stopStagePoll()       {
    if (this.stagePollTimer !== null) {
      window.clearInterval(this.stagePollTimer);
      this.stagePollTimer = null;
    }
  }

          renderStageBadge(status                             )                                {
    switch (status) {
      case "completed":
        return { cls: "ev-stg-badge--done", text: "DONE" };
      case "running":
        return { cls: "ev-stg-badge--run", text: "RUNNING" };
      case "needs_review":
        return { cls: "ev-stg-badge--review", text: "READY FOR REVIEW" };
      case "failed":
        return { cls: "ev-stg-badge--fail", text: "FAILED" };
      default:
        return { cls: "ev-stg-badge--wait", text: "QUEUED" };
    }
  }

         async refreshStageMonitor(targetPid        , isPolling = false)                {
    const listEl = document.getElementById("ev-stepper-rows");
    const titleEl = document.getElementById("ev-stepper-title");
    const subEl = document.getElementById("ev-stepper-sub");
    const statusPill = document.getElementById("ev-stepper-status-pill");
    const ctaLink = document.getElementById("ev-stepper-cockpit-cta")                            ;
    if (!listEl) return;

    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(targetPid)}/stages`);
      if (!res.ok) return;
      const data = (await res.json())                         ;
      const elapsedSec = ((Date.now() - this.monitorStartMs) / 1000).toFixed(1);

      if (titleEl) {
        titleEl.textContent = data.business_name || data.project_id;
      }
      if (subEl) {
        subEl.textContent = `${data.primary_url || data.project_id} · Elapsed ${elapsedSec}s`;
      }
      if (ctaLink) {
        ctaLink.href = `/review/${encodeURIComponent(data.project_id)}`;
      }
      if (statusPill) {
        statusPill.textContent = data.project_status.toUpperCase();
        statusPill.className = `badge ${
          data.project_status === "approved"
            ? "badge-green"
            : data.project_status === "failed"
              ? "badge-red"
              : data.project_status === "running"
                ? "badge-blue"
                : "badge-amber"
        }`;
      }

      listEl.innerHTML = data.stages
        .map((st) => {
          const b = this.renderStageBadge(st.status);
          return (
            `<div class="ev-stepper-row ev-stepper-row--${this.escapeHtml(st.status)}">` +
            `<div class="ev-stepper-num">0${st.step}</div>` +
            `<div class="ev-stepper-body">` +
            `<div class="ev-stepper-top">` +
            `<strong>${this.escapeHtml(st.plain_title)}</strong>` +
            `<span class="ev-stepper-tech">${this.escapeHtml(st.pdf_spec)}</span>` +
            `</div>` +
            `<p class="ev-stepper-desc">${this.escapeHtml(st.plain_analogy)}</p>` +
            `<div class="ev-stepper-ev">${this.escapeHtml(st.evidence)}</div>` +
            `</div>` +
            `<span class="ev-stg-badge ${b.cls}">${b.text}</span>` +
            `</div>`
          );
        })
        .join("");

      if (isPolling && data.project_status !== "running") {
        this.stopStagePoll();
        const doneMsg =
          data.project_status === "failed"
            ? `Pipeline halted for ${data.project_id}; review stage trace.`
            : `All stages processed for ${data.project_id}. Ready for review!`;
        this.showToast(doneMsg, data.project_status === "failed" ? "err" : "ok");
      }
    } catch {
      // Transient polling failures keep waiting until timeout or close
    }
  }
}

                
                    
                                           
                                                 
                                                                            
                                          
                                                                       
                                   
                                        
                                        
                                       
                                        
                                                               
                                       
                                                                               
                                  
                                    
                                                
   
 

function bootEditVistaStudio()       {
  const rootEl = document.body;
  const pid = rootEl?.getAttribute("data-project-id") ?? "";
  const controller = new EditVistaStudioController(pid);
  window.__evStudio = controller;

  window.openTab = (evt       , tabId        )       => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
    const target = evt.currentTarget                      ;
    target?.classList.add("active");
    document.getElementById(tabId)?.classList.add("active");
  };

  window.confirmRights = async (assetFile        , confirmed         )                => {
    const res = await fetch(`/api/projects/${encodeURIComponent(pid)}/confirm-rights`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ asset_file: assetFile, confirmed }),
    });
    if (res.ok) {
      window.location.reload();
    } else {
      const err = (await res.json())                       ;
      controller.showToast(`Rights error: ${err.detail ?? "Failed"}`, "err");
    }
  };

  window.confirmAllRights = async ()                => {
    await controller.confirmAllRights();
  };

  window.verifyFact = async (claimKey        , verified         )                => {
    const res = await fetch(`/api/projects/${encodeURIComponent(pid)}/verify-fact`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ claim_key: claimKey, verified }),
    });
    if (res.ok) {
      window.location.reload();
    } else {
      const err = (await res.json())                       ;
      controller.showToast(`Fact update error: ${err.detail ?? "Failed"}`, "err");
    }
  };

  window.resumeJob = async ()                => {
    const res = await fetch(`/api/projects/${encodeURIComponent(pid)}/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = (await res.json())                                            ;
    if (res.ok) {
      controller.showToast(`Resumed pipeline for ${data.project_id ?? pid}`, "ok");
      await controller.openStageMonitor(data.project_id ?? pid, true);
    } else {
      controller.showToast(`Resume failed: ${data.detail ?? "Error"}`, "err");
    }
  };

  window.openStageMonitor = async (targetPid        , autoPoll = false)                => {
    await controller.openStageMonitor(targetPid || pid, autoPoll);
  };

  window.closeStageMonitor = ()       => {
    controller.closeStageMonitor();
  };

  window.togglePipelineGuide = ()       => {
    controller.togglePipelineGuide();
  };

  window.focusBlueprintStage = (step        )       => {
    controller.focusBlueprintStage(step);
  };

  window.approveRelease = async ()                => {
    const opInput = document.getElementById("ev-operator-input")                           ;
    const notesInput = document.getElementById("ev-notes-input")                           ;
    const operator = opInput?.value.trim() || "Senior Operator";
    const notes = notesInput?.value.trim() || "Approved via Monograph Studio Cockpit";
    const res = await fetch(`/api/projects/${encodeURIComponent(pid)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operator_name: operator, notes }),
    });
    const data = (await res.json())                                                 ;
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

  window.submitRevision = async ()                => {
    const secEl = document.getElementById("section-select")                            ;
    const markupEl = document.getElementById("section-markup")                              ;
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
    const data = (await res.json())                       ;
    if (res.ok) {
      controller.showToast(`Section #${sec} revised; sibling hashes preserved.`, "ok");
      const frame = document.querySelector                   (".preview-frame");
      if (frame) {
        frame.src = `/preview/${encodeURIComponent(pid)}/standalone.html?t=${Date.now()}`;
      }
      await controller.refreshDoDLedger();
      await controller.loadSelectedSectionMarkup();
    } else {
      controller.showToast(`Revision rejected: ${data.detail ?? "Invalid markup"}`, "err");
    }
  };

  window.loadGhlExport = async ()                => {
    const cdnEl = document.getElementById("ghl-cdn-input")                           ;
    const cdnInput = cdnEl?.value.trim() ?? "";
    const qs = cdnInput ? `?cdn_base_url=${encodeURIComponent(cdnInput)}` : "";
    const res = await fetch(`/api/projects/${encodeURIComponent(pid)}/ghl-export${qs}`);
    const data = (await res.json())                                           ;
    if (!res.ok) {
      controller.showToast(`GHL export failed: ${data.detail ?? "Error"}`, "err");
      return;
    }
    const out = document.getElementById("ghl-code-output")                              ;
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

  window.copyGhlSnippet = async ()                => {
    const out = document.getElementById("ghl-code-output")                              ;
    if (!out) return;
    if (!out.value.trim()) {
      await window.loadGhlExport();
    }
    if (out.value.trim()) {
      await navigator.clipboard.writeText(out.value);
      controller.showToast("Scoped GHL snippet copied to clipboard.", "ok");
    }
  };

  window.runStoragePrune = async (mode                  )                => {
    await controller.runStoragePrune(mode);
  };

  const deriveSlug = (u        , n        )         => {
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

  const deriveName = (u        , slugVal        )         => {
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

  const newPidEl = document.getElementById("new-pid")                           ;
  const newNameEl = document.getElementById("new-name")                           ;
  const newUrlEl = document.getElementById("new-url")                           ;

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

  window.createProject = async ()                => {
    const pidEl = document.getElementById("new-pid")                           ;
    const nameEl = document.getElementById("new-name")                           ;
    const urlEl = document.getElementById("new-url")                           ;
    const runNowEl = document.getElementById("new-run-now")                           ;
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
      const created = (await res.json())                                                  ;
      const resolvedPid = created.project_id ?? newPid;
      if (created.job_started) {
        controller.showToast(`Synthesis started for ${resolvedPid}. Watching all 9 stages live.`, "ok");
        await controller.openStageMonitor(resolvedPid, true);
      } else {
        window.location.reload();
      }
    } else {
      const d = (await res.json())                       ;
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
})();
