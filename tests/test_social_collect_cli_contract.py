"""Contract tests: the gallery-dl command we build must be accepted by the REAL gallery-dl CLI.

Every other social test injects a fake `runner`, so invalid flags (e.g. the non-existent
`--date-after` / `--whitelist`) were never caught and every live run exited with code 2.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

from engine.social_collect import (
    _build_gallery_dl_cmd,
    _execute_subprocess,
    classify_social_failure,
    collect_social,
)

gdl_option = pytest.importorskip("gallery_dl.option")


def _cmd(tmp_path: Path, *, dry_run: bool, platform: str = "facebook") -> list[str]:
    return _build_gallery_dl_cmd(
        executable="gallery-dl",
        cutoff_date="2025-11-19",
        max_files=40,
        http_timeout=20,
        sleep_request=3.0,
        sleep_seconds=1.0,
        archive_path=tmp_path / "archive.txt",
        stage=tmp_path,
        platform=platform,
        url="https://www.facebook.com/profile.php?id=100095781630115",
        dry_run=dry_run,
    )


@pytest.mark.parametrize("dry_run", [True, False])
def test_built_command_is_accepted_by_real_gallery_dl_parser(
    tmp_path: Path, dry_run: bool
) -> None:
    parser = gdl_option.build_parser()
    # argparse raises SystemExit(2) on unrecognized arguments.
    args = parser.parse_args(_cmd(tmp_path, dry_run=dry_run)[1:])
    assert args.urls == ["https://www.facebook.com/profile.php?id=100095781630115"]


def test_date_window_uses_filter_with_early_abort_and_platform_whitelist(tmp_path: Path) -> None:
    cmd = _cmd(tmp_path, dry_run=False, platform="instagram")
    assert "--date-after" not in cmd
    assert "--whitelist" not in cmd
    filt = cmd[cmd.index("--filter") + 1]
    assert "datetime(2025, 11, 19)" in filt
    assert "abort()" in filt  # feeds are newest-first: stop at the first post older than cutoff
    assert cmd[cmd.index("-o") + 1] == "whitelist=instagram"


def test_cli_usage_error_is_classified_as_extractor_misconfigured() -> None:
    out = "gallery-dl: error: unrecognized arguments: --date-after"
    assert classify_social_failure(2, out) == "extractor_misconfigured"


def test_instagram_login_wall_redirect_is_classified_login_required() -> None:
    out = "[instagram][error] HTTP redirect to login page (https://www.instagram.com/accounts/login/)"
    assert classify_social_failure(1, out) == "login_required"


def test_execute_subprocess_places_no_log_inside_stage_and_kills_tree_on_timeout(
    tmp_path: Path,
) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    # Child python spawns a grandchild holding stdout open briefly, then writes an image first.
    img_buf = io.BytesIO()
    Image.new("RGB", (32, 32), color=(40, 90, 140)).save(img_buf, format="JPEG")
    img_bytes = img_buf.getvalue()
    script = (
        "import pathlib, subprocess, sys, time; "
        f"pathlib.Path({str(stage / 'partial.jpg')!r}).write_bytes({img_bytes!r}); "
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)']); "
        "time.sleep(10)"
    )
    ret, out = _execute_subprocess([sys.executable, "-c", script], stage, timeout=1, runner=None)
    assert ret == 124
    # Must NEVER leave a lockable log file inside `stage` (triggers WinError 32 on Windows).
    assert list(stage.glob("log-*.txt")) == []
    assert (stage / "partial.jpg").is_file()
    _ = out


def test_parse_instagram_alt_metadata_extracts_verified_date_and_author() -> None:
    from engine.social_collect import parse_instagram_alt_metadata

    parsed = parse_instagram_alt_metadata(
        "Photo by 26 Paws | Dog Grooming Salon on November 16, 2026. "
        "May be an image of Norwich terrier, cocker spaniel."
    )
    assert parsed["author"] == "26 Paws | Dog Grooming Salon"
    assert parsed["post_date"] == "2026-11-16T00:00:00+00:00"
    assert parsed["post_date_verified"] is True

    vid = parse_instagram_alt_metadata("Video by 26 Paws on October 03, 2026.")
    assert vid["author"] == "26 Paws"
    assert vid["post_date"] == "2026-10-03T00:00:00+00:00"
    assert vid["post_date_verified"] is True


def test_instagram_public_fallback_collects_within_cutoff_and_strips_exif(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rights import check_used_assets_audit_signatures, confirm_asset_rights

    import engine.social_collect as sc

    project = tmp_path / "26paws"
    (project / "research").mkdir(parents=True)

    im = Image.new("RGB", (64, 64), color=(10, 80, 140))
    exif = Image.Exif()
    exif[0x010E] = "Private Camera Note"
    buf = io.BytesIO()
    im.save(buf, format="JPEG", exif=exif.tobytes())
    raw_jpeg = buf.getvalue()

    monkeypatch.setattr(sc.shutil, "which", lambda _exe: "gallery-dl")

    def fake_exec(cmd: list[str], stage: Path, *, timeout: int, runner: object) -> tuple[int, str]:
        _ = (cmd, stage, timeout, runner)
        return 4, "[instagram][error] NotFoundError: Requested user could not be found"

    monkeypatch.setattr(sc, "_execute_subprocess", fake_exec)
    monkeypatch.setattr(
        sc,
        "_fetch_public_instagram_items",
        lambda url, *, max_files, http_timeout: {
            "login_required": False,
            "items": [
                {
                    "post_url": "https://www.instagram.com/p/OLD_2024/",
                    "image_bytes": raw_jpeg,
                    "extension": ".jpg",
                    "author": "26 Paws | Dog Grooming Salon",
                    "post_date": "2024-05-02T00:00:00+00:00",
                    "post_date_verified": True,
                },
                {
                    "post_url": "https://www.instagram.com/p/NEW_2026/",
                    "image_bytes": raw_jpeg,
                    "extension": ".jpg",
                    "author": "26 Paws | Dog Grooming Salon",
                    "post_date": "2026-11-16T00:00:00+00:00",
                    "post_date_verified": True,
                },
            ],
        },
    )

    res = collect_social(
        project,
        "instagram",
        "https://www.instagram.com/26.Paws/",
        max_files=10,
        days_limit=365,
        i_have_permission=True,
    )
    assert res["status"] == "collected_needs_review"
    assert res["files_added"] == 1
    manifest = json.loads(
        (project / "research" / "social-media-manifest.json").read_text(encoding="utf-8")
    )
    assert len(manifest) == 1
    assert manifest[0]["source_post_url"] == "https://www.instagram.com/p/NEW_2026/"
    assert manifest[0]["post_date_verified"] is True
    assert manifest[0]["rights_confirmed_for_preview"] is False

    # Rights confirmation & audit verification must work on social-media-manifest assets too.
    opt_rel = manifest[0]["optimized_file"]
    confirm_asset_rights(
        project,
        all_assets=True,
        basis="owner_permission",
        operator="QA Lead",
        evidence="Written email permission from 26 Paws",
    )
    assert check_used_assets_audit_signatures(project, [opt_rel]) == []


def test_instagram_public_fallback_refuses_login_wall_without_bypass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.social_collect as sc

    project = tmp_path / "private_salon"
    (project / "research").mkdir(parents=True)
    monkeypatch.setattr(sc.shutil, "which", lambda _exe: "gallery-dl")
    monkeypatch.setattr(
        sc,
        "_execute_subprocess",
        lambda *a, **kw: (4, "[instagram][error] NotFoundError: Requested user could not be found"),
    )
    monkeypatch.setattr(
        sc,
        "_fetch_public_instagram_items",
        lambda url, *, max_files, http_timeout: {"login_required": True, "items": []},
    )
    res = collect_social(
        project,
        "instagram",
        "https://www.instagram.com/private_salon/",
        i_have_permission=True,
    )
    assert res["status"] == "review_needed"
    assert res["reason"] == "login_required"
    assert res["files_added"] == 0


def test_dump_json_ignores_type6_queue_hints_so_fallback_triggers() -> None:
    from engine.social_collect import parse_dump_json_metadata

    raw = json.dumps(
        [
            [
                6,
                "https://www.instagram.com/26.Paws/posts/",
                {"category": "instagram", "subcategory": "user"},
            ],
        ]
    )
    assert parse_dump_json_metadata(raw) == []


def test_instagram_public_fallback_triggers_when_step1_returns_0_and_step2_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.social_collect as sc

    project = tmp_path / "26paws-two-step"
    (project / "research").mkdir(parents=True)

    im = Image.new("RGB", (48, 48), color=(30, 100, 160))
    buf = io.BytesIO()
    im.save(buf, format="JPEG")
    raw_jpeg = buf.getvalue()

    monkeypatch.setattr(sc.shutil, "which", lambda _exe: "gallery-dl")

    def two_step_exec(
        cmd: list[str], stage: Path, *, timeout: int, runner: object
    ) -> tuple[int, str]:
        _ = (stage, timeout, runner)
        if "--dump-json" in cmd:
            return 0, json.dumps(
                [[6, "https://www.instagram.com/26.Paws/posts/", {"category": "instagram"}]]
            )
        return 4, "[instagram][error] NotFoundError: Requested user could not be found"

    monkeypatch.setattr(sc, "_execute_subprocess", two_step_exec)
    monkeypatch.setattr(
        sc,
        "_fetch_public_instagram_items",
        lambda url, *, max_files, http_timeout: {
            "login_required": False,
            "items": [
                {
                    "post_url": "https://www.instagram.com/p/Df0RW7QASnX/",
                    "image_bytes": raw_jpeg,
                    "extension": ".jpg",
                    "author": "26 Paws | Dog Grooming Salon",
                    "post_date": "2026-11-16T00:00:00+00:00",
                    "post_date_verified": True,
                }
            ],
        },
    )

    res = collect_social(
        project,
        "instagram",
        "https://www.instagram.com/26.Paws/",
        max_files=5,
        days_limit=365,
        i_have_permission=True,
    )
    assert res["status"] == "collected_needs_review"
    assert res["files_added"] == 1
    assert res.get("collection_method") == "public_instagram_browser_embed"


def test_extract_instagram_embed_image_parses_ssr_embed_and_flags_login_wall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import engine.social_collect as sc

    class _Resp:
        def __init__(self, status_code: int, url: str, text: str) -> None:
            self.status_code = status_code
            self.url = url
            self.text = text

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def close(self) -> None:
            pass

    monkeypatch.setattr(sc, "safe_url", lambda u: u)
    monkeypatch.setattr(
        sc,
        "response_get",
        lambda sess, url, **kw: _Resp(
            200,
            url,
            '<html><img class="EmbeddedMediaImage" src="https://instagram.example/1080.jpg"></html>',
        ),
    )
    img_url, login_hit = sc._extract_instagram_embed_image(
        object(), "https://www.instagram.com/26.paws/p/Df0RW7QASnX/"
    )
    assert img_url == "https://instagram.example/1080.jpg"
    assert login_hit is False

    monkeypatch.setattr(
        sc,
        "response_get",
        lambda sess, url, **kw: _Resp(
            200, "https://www.instagram.com/accounts/login/?next=...", "<html></html>"
        ),
    )
    img_url, login_hit = sc._extract_instagram_embed_image(
        object(), "https://www.instagram.com/p/PRIVATE/"
    )
    assert img_url is None
    assert login_hit is True


def test_pipeline_cli_social_permission_flag_is_opt_in() -> None:
    from app.pipeline import build_arg_parser

    parser = build_arg_parser()
    default_args = parser.parse_args(["--url", "https://example.com", "--name", "Test"])
    assert default_args.i_have_social_permission is False
    opted_args = parser.parse_args(
        ["--url", "https://example.com", "--name", "Test", "--i-have-social-permission"]
    )
    assert opted_args.i_have_social_permission is True
