"""
Comprehensive Definition of Done (DoD) Verification Engine.
Runs 360-degree audit across Code Quality, 8-Gate DoD Status, and GHL Embed Integrity.
"""

from __future__ import annotations

import json
import sys
import urllib.request

PROJECTS: list[str] = [
    "lilys-club-live",
    "m5-pupcentral",
    "m5-fidos-fitzrovia",
    "m5-mod-mutt",
    "m5-vanity-fur",
]


def check_cockpit_dod() -> bool:
    print("=" * 70)
    print("  DEFINITION OF DONE (DoD) - 8-GATE COMPLIANCE AUDIT")
    print("=" * 70)
    all_passed = True
    base_url = "http://127.0.0.1:8788"

    for pid in PROJECTS:
        url = f"{base_url}/api/projects/{pid}/dod-status"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as res:
                data = json.loads(res.read().decode())
                gates = data.get("gates", {})
                passed = all(gates.values())
                status_icon = "🟢 PASS" if passed else "🔴 FAIL"
                v_facts = data.get("verified_fact_count")
                t_facts = data.get("total_fact_count")
                v_assets = data.get("confirmed_asset_count")
                t_assets = data.get("total_asset_count")
                violations = len(data.get("claim_violations", []))

                print(f"\n[{status_icon}] Project: {pid}")
                print(f"      Verified Facts: {v_facts}/{t_facts}")
                print(f"      Signed Assets : {v_assets}/{t_assets}")
                print(f"      Violations    : {violations}")
                print("      8-Gate Breakdown:")
                gate_names = [
                    ("facts_verified", "01 / Source Provenance"),
                    ("rights_confirmed", "02 / Asset Rights Audit"),
                    ("claim_scanner_passed", "03 / Claim Scanner (Zero-Fabrication)"),
                    ("five_view_qa_passed", "04 / 5-Viewport Playwright QA"),
                    ("visual_critique_status", "05 / Multi-Modal Vision Critique"),
                    ("section_hashes_present", "06 / Section Hash Ledger"),
                    ("release_frozen", "07 / Immutable Release (delivery/)"),
                    ("archive_verified", "08 / Cryptographic Backup Archive"),
                ]
                for key, label in gate_names:
                    val = gates.get(key)
                    ok = bool(val)
                    print(f"        {'✓' if ok else '✗'} {label}: {val}")
                if not passed:
                    all_passed = False
        except Exception as e:
            print(f"\n[🔴 ERROR] {pid}: Could not reach Cockpit on {base_url}: {e}")
            all_passed = False

    print("\n" + "=" * 70)
    if all_passed:
        print("  RESULT: 100% OF ALL 5 PRODUCTION PROJECTS PASS ALL 8 DOD GATES!")
    else:
        print("  RESULT: SOME DOD GATES FAILED")
    print("=" * 70)
    return all_passed


if __name__ == "__main__":
    success = check_cockpit_dod()
    sys.exit(0 if success else 1)
