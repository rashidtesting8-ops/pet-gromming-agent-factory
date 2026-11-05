"""GoHighLevel (GHL) custom code exporter with CSS selector scoping and IIFE JS isolation."""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup, Doctype, Tag

_GLOBAL_LEAK_RE = re.compile(
    r"\b(?:window|document|globalThis)\s*(?:\.\s*[A-Za-z_$][A-Za-z0-9_$]*|\[\s*['\"][^'\"]+['\"]\s*\])\s*=(?!=)"
)

_CSS_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/")
_ROOT_LEADING_RE = re.compile(r"^(?::root|html|body)\b", re.I)


class GlobalLeakageError(ValueError):
    """Raised when candidate JavaScript assigns properties directly onto window.* or document.*."""


class UnscopedCSSError(ValueError):
    """Raised when any CSS rule selector lacks the mandatory root scoping prefix."""


def _atomic_write_text(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, target)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _scope_single_selector(selector: str, root_selector: str) -> str:
    sel = " ".join(selector.strip().split())
    if not sel:
        return root_selector

    if sel.startswith(root_selector):
        return sel

    # Move :root, html, or body directly to the root container ID
    if sel.lower() in (":root", "html", "body"):
        return root_selector

    # Replace leading :root / html / body in compound selectors (e.g., "body .hero")
    if _ROOT_LEADING_RE.match(sel):
        rest = _ROOT_LEADING_RE.sub("", sel, count=1).strip()
        return f"{root_selector} {rest}" if rest else root_selector

    return f"{root_selector} {sel}"


def _scope_selector_list(selector_group: str, root_selector: str) -> str:
    raw_parts = [part.strip() for part in selector_group.split(",") if part.strip()]
    scoped_parts: list[str] = []
    for part in raw_parts:
        scoped = _scope_single_selector(part, root_selector)
        if scoped not in scoped_parts:
            scoped_parts.append(scoped)
    return ", ".join(scoped_parts)


def _split_top_level_css_blocks(css: str) -> list[tuple[str, str]]:
    """Parse CSS into a sequence of (header_or_statement, body_without_outer_braces)."""
    blocks: list[tuple[str, str]] = []
    n = len(css)
    i = 0
    header_start = 0

    while i < n:
        ch = css[i]
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < n:
                if css[i] == "\\":
                    i += 2
                    continue
                if css[i] == quote:
                    break
                i += 1
        elif ch == ";" and "{" not in css[header_start:i]:
            stmt = css[header_start : i + 1].strip()
            if stmt:
                blocks.append((stmt, ""))
            header_start = i + 1
        elif ch == "{":
            header = css[header_start:i].strip()
            depth = 1
            body_start = i + 1
            i += 1
            while i < n and depth > 0:
                c = css[i]
                if c in ("'", '"'):
                    q = c
                    i += 1
                    while i < n:
                        if css[i] == "\\":
                            i += 2
                            continue
                        if css[i] == q:
                            break
                        i += 1
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                i += 1
            body = css[body_start : i - 1].strip()
            blocks.append((header, body))
            header_start = i
            continue
        i += 1

    return blocks


def scope_css(css_text: str, root_selector: str) -> str:
    """Prefix every CSS rule selector with root_selector and move :root vars to root_selector."""
    cleaned = _CSS_COMMENT_RE.sub("", css_text)
    blocks = _split_top_level_css_blocks(cleaned)
    out: list[str] = []

    for header, body in blocks:
        if not body and header.endswith(";"):
            out.append(header)
            continue

        lower_hdr = header.lower()
        if lower_hdr.startswith(("@media", "@supports", "@container")):
            nested_scoped = scope_css(body, root_selector)
            indented = "\n".join(f"  {line}" for line in nested_scoped.splitlines() if line.strip())
            out.append(f"{header} {{\n{indented}\n}}")
        elif lower_hdr.startswith(("@keyframes", "@-webkit-keyframes", "@font-face")):
            out.append(f"{header} {{\n  {body}\n}}")
        else:
            scoped_header = _scope_selector_list(header, root_selector)
            declarations = "; ".join(
                d.strip() for d in body.split(";") if d.strip()
            )
            if declarations:
                declarations += ";"
            out.append(f"{scoped_header} {{ {declarations} }}")

    return "\n".join(out)


def find_unscoped_selectors(css_text: str, root_selector: str) -> list[str]:
    """Return any style rule selector in css_text that does not begin with root_selector."""
    cleaned = _CSS_COMMENT_RE.sub("", css_text)
    blocks = _split_top_level_css_blocks(cleaned)
    offending: list[str] = []

    for header, body in blocks:
        if not body and header.endswith(";"):
            continue
        lower_hdr = header.lower()
        if lower_hdr.startswith(("@media", "@supports", "@container")):
            offending.extend(find_unscoped_selectors(body, root_selector))
        elif lower_hdr.startswith(("@keyframes", "@-webkit-keyframes", "@font-face")):
            continue
        else:
            for part in header.split(","):
                sel = part.strip()
                if not sel:
                    continue
                if not sel.startswith(root_selector):
                    offending.append(sel)

    return offending


def check_no_global_js_leakage(js_text: str) -> None:
    """Raise GlobalLeakageError if JS assigns directly to window.*, document.*, or globalThis.*."""
    match = _GLOBAL_LEAK_RE.search(js_text)
    if match:
        raise GlobalLeakageError(
            f"Prohibited global assignment detected in script: {match.group(0)!r}"
        )


def isolate_javascript(js_text: str, root_id: str) -> str:
    """Wrap scripts in a strict IIFE with a MutationObserver fallback for dynamic GHL mounting."""
    check_no_global_js_leakage(js_text)
    body = js_text.strip()
    return (
        "(function(){ 'use strict';\n"
        f"  var ROOT_ID = {root_id!r};\n"
        "  var initialized = false;\n"
        "  function init(root) {\n"
        "    if (initialized || !root) { return; }\n"
        "    initialized = true;\n"
        f"    {body}\n"
        "  }\n"
        "  var existing = document.getElementById(ROOT_ID);\n"
        "  if (existing) {\n"
        "    init(existing);\n"
        "  } else if (typeof MutationObserver !== 'undefined') {\n"
        "    var observer = new MutationObserver(function() {\n"
        "      var el = document.getElementById(ROOT_ID);\n"
        "      if (el) {\n"
        "        observer.disconnect();\n"
        "        init(el);\n"
        "      }\n"
        "    });\n"
        "    observer.observe(document.documentElement || document.body, {\n"
        "      childList: true,\n"
        "      subtree: true\n"
        "    });\n"
        "  }\n"
        "})();"
    )


def sanitize_and_extract_markup(html_text: str) -> tuple[str, list[str], list[str]]:
    """Strip DOCTYPE, html, head, body tags and extract inline <style> and <script> blocks."""
    soup = BeautifulSoup(html_text, "html.parser")

    for item in list(soup.contents):
        if isinstance(item, Doctype):
            item.extract()

    inline_styles: list[str] = []
    for style_tag in soup.find_all("style"):
        inline_styles.append(style_tag.get_text("\n"))
        style_tag.decompose()

    for link_tag in soup.find_all("link"):
        link_tag.decompose()

    inline_scripts: list[str] = []
    for script_tag in soup.find_all("script"):
        script_text = script_tag.get_text("\n").strip()
        if script_text:
            inline_scripts.append(script_text)
        script_tag.decompose()

    body = soup.find("body")
    if isinstance(body, Tag):
        inner_markup = "".join(str(child) for child in body.contents).strip()
    else:
        for wrapper_name in ("head", "html"):
            for tag in soup.find_all(wrapper_name):
                tag.unwrap()
        inner_markup = str(soup).strip()

    return inner_markup, inline_styles, inline_scripts


def export_ghl_snippet(
    project_folder: str | Path,
    *,
    business_id: str | None = None,
) -> str:
    """Build a self-contained, CSS-scoped, IIFE-isolated GHL snippet at delivery/ghl-ready.html."""
    project_root = Path(project_folder).resolve()
    website_dir = project_root / "website"
    index_path = website_dir / "index.html"
    if not index_path.is_file():
        raise ValueError(f"Approved source HTML not found: {index_path}")

    biz_id = business_id or project_root.name
    root_id = f"ghl-ev-engine-root-{biz_id}"
    root_selector = f"#{root_id}"

    raw_html = index_path.read_text(encoding="utf-8")
    inner_markup, inline_styles, inline_scripts = sanitize_and_extract_markup(raw_html)

    css_chunks: list[str] = []
    css_dir = website_dir / "css"
    if css_dir.is_dir():
        for css_file in sorted(css_dir.glob("*.css")):
            if css_file.is_file() and not css_file.is_symlink():
                css_chunks.append(css_file.read_text(encoding="utf-8"))
    css_chunks.extend(inline_styles)

    combined_raw_css = "\n".join(c for c in css_chunks if c.strip())
    scoped_css = scope_css(combined_raw_css, root_selector) if combined_raw_css else ""
    unscoped = find_unscoped_selectors(scoped_css, root_selector)
    if unscoped:
        raise UnscopedCSSError(f"Unscoped CSS selectors detected: {unscoped}")

    js_chunks: list[str] = []
    js_dir = website_dir / "js"
    if js_dir.is_dir():
        for js_file in sorted(js_dir.glob("*.js")):
            if js_file.is_file() and not js_file.is_symlink():
                js_chunks.append(js_file.read_text(encoding="utf-8"))
    js_chunks.extend(inline_scripts)

    combined_raw_js = "\n".join(j for j in js_chunks if j.strip())
    isolated_js = isolate_javascript(combined_raw_js, root_id)

    parts: list[str] = [f'<div id="{root_id}">']
    if scoped_css:
        parts.append(f"<style>\n{scoped_css}\n</style>")
    parts.append(inner_markup)
    parts.append(f"<script>\n{isolated_js}\n</script>")
    parts.append("</div>\n")

    final_output = "\n".join(parts)
    out_path = project_root / "delivery" / "ghl-ready.html"
    _atomic_write_text(out_path, final_output)
    return final_output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export approved website into a scoped GoHighLevel custom code snippet."
    )
    parser.add_argument("--project", required=True, help="Path to project directory")
    parser.add_argument("--business-id", default=None, help="Optional explicit business ID")
    args = parser.parse_args()
    export_ghl_snippet(args.project, business_id=args.business_id)


if __name__ == "__main__":
    main()
