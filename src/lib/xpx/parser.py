from __future__ import annotations

import argparse

from lib.common.constants import VERSION
from lib.xpx.parsers import accounts, agents, apply, models, providers, system

_MODULES = (providers, models, apply, accounts, system, agents)


def build_parser(prog: str = "xpx") -> argparse.ArgumentParser:
    """Build the complete ``xpx`` argument parser.

    Each command group registers itself, so adding a command means touching one
    small module instead of growing a single function.
    """
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Unified AI Agent Provider Control Plane",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    subparsers = parser.add_subparsers(dest="subcommand", metavar="<command>")
    for module in _MODULES:
        module.register(subparsers)
    return parser
