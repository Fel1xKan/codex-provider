#!/usr/bin/env python3
"""Extract the CHANGELOG section for the release being published.

The release workflow uses this script to build the GitHub release body from
CHANGELOG.md, so the notes a user sees in `cpx upgrade` are exactly the notes
reviewed in the pull request that made the change.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from lib.common.constants import VERSION  # noqa: E402
from lib.common.errors import SwitchError  # noqa: E402
from lib.common.release_notes import (  # noqa: E402
    changelog_section,
    require_changelog_section,
)

CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        default=VERSION,
        help=f"Version to extract, default: the packaged version ({VERSION})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only verify that the section exists",
    )
    args = parser.parse_args()

    text = CHANGELOG.read_text(encoding="utf-8")
    try:
        if args.check:
            section = require_changelog_section(args.version, text)
            print(f"CHANGELOG.md has notes for {args.version} ({len(section)} bytes)")
            return 0
        section = changelog_section(args.version, text)
    except SwitchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if section is None:
        print(
            f"error: CHANGELOG.md has no section for version {args.version}; "
            "add one before releasing",
            file=sys.stderr,
        )
        return 1
    print(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
