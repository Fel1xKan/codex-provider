from __future__ import annotations

from typing import Any

from lib.common import release_notes, self_upgrade
from lib.common.constants import VERSION


def run_upgrade(args: Any) -> int:
    check = getattr(args, "check", False)
    notes_only = getattr(args, "notes", False)
    dry_run = getattr(args, "dry_run", False)

    payload = self_upgrade.fetch_latest_release(self_upgrade.DEFAULT_REPOSITORY)
    plan = self_upgrade.build_upgrade_plan(
        self_upgrade.DEFAULT_REPOSITORY,
        "xpx",
        VERSION,
        payload,
    )

    if notes_only:
        release_notes.print_notes(plan)
        return 0

    if check or dry_run:
        print(f"current: {plan.current_version}")
        print(f"latest:  {plan.latest_version}")
        print(f"asset:   {plan.asset_name}")
        if not plan.update_available:
            print("up to date")
        else:
            print("would upgrade" if dry_run else "update available")
        if plan.update_available:
            release_notes.print_notes(plan)
        return 0

    if plan.update_available:
        release_notes.print_notes(plan)
    target = self_upgrade.current_executable()
    return self_upgrade.perform_upgrade(plan, target)
