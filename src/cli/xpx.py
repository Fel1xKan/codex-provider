#!/usr/bin/env python3
from __future__ import annotations

import sys
from collections.abc import Sequence

from lib.common.errors import SwitchError
from lib.xpx.parser import build_parser


def main(argv: Sequence[str] | None = None) -> int:
    effective_args = list(argv) if argv is not None else sys.argv[1:]

    # 1. First-run legacy migration check
    if not any(
        a in effective_args
        for a in ("-V", "--version", "-h", "--help", "migrate", "--dry-run")
    ):
        from lib.xpx.commands.cmd_import_export import auto_migrate_legacy_if_needed

        auto_migrate_legacy_if_needed()

    # 2. Main xpx parser execution
    parser = build_parser(prog="xpx")
    args = parser.parse_args(effective_args)

    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    try:
        return args.func(args) or 0
    except SwitchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOperation cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
