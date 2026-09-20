from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import pytest

import cli.codex_provider as cp
import lib.common.release_notes as notes
import lib.common.self_upgrade as self_upgrade
from lib.common.constants import VERSION

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

SAMPLE = """# Changelog

## [Unreleased]

## [1.2.0] - 2026-01-02

### Added

- A **bold** feature and a [link](https://example.com).
- `code span` support.

## [1.1.0] - 2026-01-01

### Fixed

- Something else.

[Unreleased]: https://example.com/compare
[1.2.0]: https://example.com/1.2.0
[1.1.0]: https://example.com/1.1.0
"""


def test_changelog_section_extracts_only_the_matching_version() -> None:
    section = notes.changelog_section("1.2.0", SAMPLE)

    assert section is not None
    assert "A **bold** feature" in section
    assert "Something else" not in section
    assert "[Unreleased]:" not in section
    assert "[1.2.0]:" not in section
    # The release date on the heading line is not note content.
    assert not section.startswith("- 2026")


def test_changelog_section_of_the_oldest_release_stops_before_links() -> None:
    section = notes.changelog_section("1.1.0", SAMPLE)

    assert section is not None
    assert "Something else" in section
    assert "https://example.com/1.1.0" not in section


def test_changelog_section_returns_none_for_unknown_version() -> None:
    assert notes.changelog_section("9.9.9", SAMPLE) is None


def test_require_changelog_section_reports_a_missing_entry() -> None:
    with pytest.raises(self_upgrade.SwitchError, match="no section for version 9.9.9"):
        notes.require_changelog_section("9.9.9", SAMPLE)


def test_render_notes_flattens_markdown() -> None:
    lines = notes.render_notes(
        "### Added\n\n- A **bold** feature and a [link](https://example.com).\n"
        "- `code span` support.\n\n* star bullet\n"
    )

    assert lines == [
        "Added",
        "",
        "- A bold feature and a link.",
        "- code span support.",
        "",
        "- star bullet",
    ]


def test_render_notes_keeps_identifiers_with_underscores() -> None:
    """Underscores inside an identifier are not emphasis."""

    lines = notes.render_notes(
        "- cpx models update --set supported_reasoning_levels=low,high\n"
        "- _real emphasis_ stays removable\n"
        "- `a_b_c` in a code span is untouched\n"
    )

    assert lines == [
        "- cpx models update --set supported_reasoning_levels=low,high",
        "- real emphasis stays removable",
        "- a_b_c in a code span is untouched",
    ]


def test_render_notes_drops_asterisks_only_when_they_pair() -> None:
    lines = notes.render_notes("- A **bold** word and a bare * star\n")

    assert lines == ["- A bold word and a bare * star"]


def test_render_notes_drops_the_generated_full_changelog_line() -> None:
    """Old releases carry GitHub's auto-generated trailer; our footer replaces it."""

    lines = notes.render_notes(
        "## What's Changed\n"
        "* Add a flag by @dev in #12\n"
        "\n"
        "**Full Changelog**: https://example.com/compare/v1...v2\n"
    )

    assert lines == ["What's Changed", "- Add a flag by @dev in #12"]


def test_render_notes_truncates_long_bodies() -> None:
    body = "\n".join(f"- item {index}" for index in range(10))

    lines = notes.render_notes(body, max_lines=4)

    assert lines[:4] == ["- item 0", "- item 1", "- item 2", "- item 3"]
    assert lines[-1] == "... and 6 more lines"


def test_render_notes_handles_empty_bodies() -> None:
    assert notes.render_notes(None) == []
    assert notes.render_notes("") == []
    assert notes.render_notes("<!-- only a comment -->") == []


def test_print_notes_falls_back_to_the_release_url(capsys) -> None:
    plan = self_upgrade.UpgradePlan(
        current_version="1.0.0",
        latest_version="1.1.0",
        release_url="https://example.com/release",
        asset_name="cpx-1.1.0-linux-x86_64",
        asset_url="https://example.com/cpx",
        sha256_url=None,
        update_available=True,
    )

    notes.print_notes(plan)

    assert "no release notes published" in capsys.readouterr().out


def _release_payload(body: str | None = None) -> dict[str, object]:
    platform_key = self_upgrade._platform_key()
    suffix = ".exe" if os.name == "nt" else ""
    asset_name = f"cpx-1.1.0-{platform_key}{suffix}"
    payload: dict[str, object] = {
        "tag_name": "v1.1.0",
        "html_url": "https://example.com/release",
        "name": "v1.1.0",
        "assets": [
            {
                "name": asset_name,
                "browser_download_url": "https://example.com/cpx",
            }
        ],
    }
    if body is not None:
        payload["body"] = body
    return payload


def test_build_upgrade_plan_carries_release_notes() -> None:
    payload = _release_payload(body="## Added\n\n- something new")

    plan = self_upgrade.build_upgrade_plan(
        "owner/repo", "cpx", "1.0.0", payload, legacy_name=None
    )

    assert plan.notes == "## Added\n\n- something new"
    assert plan.release_name == "v1.1.0"


def test_build_upgrade_plan_tolerates_a_missing_body() -> None:
    payload = _release_payload()

    plan = self_upgrade.build_upgrade_plan(
        "owner/repo", "cpx", "1.0.0", payload, legacy_name=None
    )

    assert plan.notes == ""


def _plan_available() -> self_upgrade.UpgradePlan:
    return self_upgrade.UpgradePlan(
        current_version="1.0.0",
        latest_version="1.1.0",
        release_url="https://example.com/release",
        asset_name="cpx-1.1.0-linux-x86_64",
        asset_url="https://example.com/cpx",
        sha256_url=None,
        update_available=True,
        notes="### Added\n\n- a new command\n",
    )


@pytest.fixture
def no_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the tests from downloading or replacing a binary."""

    def fail(*args, **kwargs):
        raise AssertionError("upgrade must not install during this test")

    monkeypatch.setattr(self_upgrade, "perform_upgrade", fail)
    monkeypatch.setattr(self_upgrade, "current_executable", lambda: Path("/bin/cpx"))


def test_upgrade_check_shows_release_notes(
    monkeypatch: pytest.MonkeyPatch, capsys, no_upgrade
) -> None:
    monkeypatch.setattr(self_upgrade, "fetch_latest_release", lambda repo: {})
    monkeypatch.setattr(
        self_upgrade,
        "build_upgrade_plan",
        lambda *args, **kwargs: _plan_available(),
    )

    assert cp.main(["upgrade", "--check"]) == 0

    out = capsys.readouterr().out
    assert "latest:  1.1.0" in out
    assert "update available" in out
    assert "what's new in 1.1.0:" in out
    assert "- a new command" in out
    assert "full notes: https://example.com/release" in out


def test_upgrade_notes_flag_prints_notes_only(
    monkeypatch: pytest.MonkeyPatch, capsys, no_upgrade
) -> None:
    monkeypatch.setattr(self_upgrade, "fetch_latest_release", lambda repo: {})
    monkeypatch.setattr(
        self_upgrade,
        "build_upgrade_plan",
        lambda *args, **kwargs: _plan_available(),
    )

    assert cp.main(["upgrade", "--notes"]) == 0

    out = capsys.readouterr().out
    assert "what's new in 1.1.0:" in out
    # `--notes` must not report or perform an upgrade.
    assert "update available" not in out
    assert "current:" not in out


def test_upgrade_check_stays_quiet_when_up_to_date(
    monkeypatch: pytest.MonkeyPatch, capsys, no_upgrade
) -> None:
    plan = self_upgrade.UpgradePlan(
        current_version="1.1.0",
        latest_version="1.1.0",
        release_url="https://example.com/release",
        asset_name="cpx-1.1.0-linux-x86_64",
        asset_url="https://example.com/cpx",
        sha256_url=None,
        update_available=False,
        notes="### Added\n\n- already installed\n",
    )
    monkeypatch.setattr(self_upgrade, "fetch_latest_release", lambda repo: {})
    monkeypatch.setattr(
        self_upgrade, "build_upgrade_plan", lambda *args, **kwargs: plan
    )

    assert cp.main(["upgrade", "--check"]) == 0

    out = capsys.readouterr().out
    assert "up to date" in out
    assert "what's new" not in out


def test_upgrade_command_exposes_notes_flag() -> None:
    """Every CLI shares one upgrade spec, so parity is structural."""

    import cli.agy_provider as ap
    import cli.claude_provider as clp
    import cli.cursor_provider as cup
    import cli.opencode_provider as op

    for module in (cp, op, ap, cup, clp):
        parser = module.build_parser()
        action = next(
            item
            for item in parser._actions
            if isinstance(item, argparse._SubParsersAction)
        )
        upgrade = action.choices["upgrade"]
        flags = {opt for item in upgrade._actions for opt in item.option_strings}
        assert {"--check", "--dry-run", "--notes"} <= flags, module.__name__


def test_release_notes_stay_short() -> None:
    """Notes are read in a terminal, so each release gets a few lines."""

    text = CHANGELOG.read_text(encoding="utf-8")
    versions = re.findall(r"^##\s+\[(\d+\.\d+\.\d+)\]", text, re.MULTILINE)
    assert versions
    for version in versions:
        lines = notes.render_notes(notes.changelog_section(version, text))
        assert lines, version
        assert len(lines) <= 12, (version, lines)


def test_release_notes_do_not_list_bug_fixes() -> None:
    """The changelog tracks new capabilities; fixes are not listed."""

    text = CHANGELOG.read_text(encoding="utf-8").lower()

    for heading in ("### fixed", "### removed", "### security"):
        assert heading not in text


def test_current_version_has_release_notes() -> None:
    """CI runs the same check, so a release can never ship empty notes."""

    section = notes.require_changelog_section(
        VERSION, CHANGELOG.read_text(encoding="utf-8")
    )

    assert section.strip()
    # Notes are read in a terminal, so they must render to plain lines.
    assert notes.render_notes(section)
