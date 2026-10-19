from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from lib.common.errors import SwitchError
from lib.xpx.adapters.base import TargetAdapter
from lib.xpx.adapters.registry import get_all_adapters

ORDERED_AGENTS = ("codex", "claude", "opencode", "agy", "pi", "cursor")


def run_agent_list(args: Any) -> int:
    adapters = get_all_adapters()
    header = (
        f"{'Agent':<10} {'Installed':<11} {'Version':<12} "
        f"{'Package / Install Source':<32} {'Binary Path'}"
    )
    print(header)
    print("-" * 88)

    for name in ORDERED_AGENTS:
        if name not in adapters:
            continue
        adp = adapters[name]
        bin_path = adp.get_binary_path()
        installed = bin_path is not None
        status_sym = "✔ Yes" if installed else "✖ No"
        version = adp.get_cli_version() or "-" if installed else "-"
        source = (
            f"{adp.package_name} (npm)"
            if adp.package_name
            else (
                adp.install_guide[:30] + "..."
                if len(adp.install_guide) > 30
                else adp.install_guide or "-"
            )
        )
        path_display = bin_path or "-"

        print(f"{name:<10} {status_sym:<11} {version:<12} {source:<32} {path_display}")

    return 0


def run_agent_install(args: Any) -> int:
    target = getattr(args, "target", None)
    install_all = getattr(args, "all", False)
    dry_run = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)
    adapters = get_all_adapters()

    if not target and not install_all:
        missing = [
            name
            for name in ORDERED_AGENTS
            if name in adapters and not adapters[name].get_binary_path()
        ]
        if missing:
            print(f"Missing agent CLI(s): {', '.join(missing)}\n")
        else:
            print("All supported agent CLIs are already installed.\n")
        print("Usage:")
        print("  xpx agent install <name>[,<name>...]  Install specific agent CLI(s)")
        print("  xpx agent install --all               Install all missing agent CLIs")
        return 0 if not missing else 1

    if target:
        target_names = [t.strip().lower() for t in target.split(",") if t.strip()]
        available = ", ".join(adapters.keys())
        for name in target_names:
            if name not in adapters:
                raise SwitchError(f"unknown agent '{name}', available: {available}")

        if len(target_names) == 1:
            target_name = target_names[0]
            adp = adapters[target_name]
            if adp.get_binary_path() and not force:
                ver = adp.get_cli_version()
                print(
                    f"✔ Agent '{target_name}' is already installed "
                    f"({ver or 'unknown'}). Use --force to reinstall."
                )
                return 0

            print(f"⏳ Installing agent '{target_name}' ({adp.display_name})...")
            ok, msg = adp.install(dry_run=dry_run)
            if ok:
                print(f"✔ {msg}")
                return 0
            print(f"✖ Failed to install '{target_name}': {msg}", file=sys.stderr)
            return 1

        targets_to_install = [
            adapters[name]
            for name in target_names
            if (not adapters[name].get_binary_path() or force)
        ]
        if not targets_to_install:
            print("✔ All requested agent CLIs are already installed.")
            return 0
    else:
        # --all mode
        targets_to_install = [
            adapters[name]
            for name in ORDERED_AGENTS
            if name in adapters and (not adapters[name].get_binary_path() or force)
        ]
        if not targets_to_install:
            print("✔ All supported agent CLIs are already installed.")
            return 0

    print(
        f"Found {len(targets_to_install)} agent CLI(s) to install: "
        f"{', '.join(a.name for a in targets_to_install)}"
    )

    failures: list[str] = []
    for adp in targets_to_install:
        print(f"\n=== Installing {adp.display_name} ({adp.name}) ===")
        ok, msg = adp.install(dry_run=dry_run)
        if ok:
            print(f"✔ {msg}")
        else:
            print(f"✖ {msg}", file=sys.stderr)
            failures.append(adp.name)

    if failures:
        fail_list = ", ".join(failures)
        print(
            f"\nwarning: {len(failures)} agent(s) failed to install: {fail_list}",
            file=sys.stderr,
        )
        return 1

    print("\n✔ Successfully processed all requested agents.")
    return 0


def _update_single_agent(
    adp: TargetAdapter, dry_run: bool
) -> tuple[str, str, bool, str, str | None, str | None]:
    old_ver = adp.get_cli_version()
    ok, msg = adp.update(dry_run=dry_run)
    new_ver = adp.get_cli_version() if ok else None
    return adp.name, adp.display_name, ok, msg, old_ver, new_ver


def run_agent_update(args: Any) -> int:
    target = getattr(args, "target", None)
    update_all = getattr(args, "all", False)
    dry_run = getattr(args, "dry_run", False)
    adapters = get_all_adapters()

    if not target and not update_all:
        installed = [
            name
            for name in ORDERED_AGENTS
            if name in adapters and adapters[name].get_binary_path()
        ]
        if installed:
            print(f"Installed agent CLI(s): {', '.join(installed)}\n")
        else:
            print("No agent CLIs are installed.\n")
        print("Usage:")
        print("  xpx agent update <name>[,<name>...]  Update specific agent CLI(s)")
        print("  xpx agent update --all               Update all installed agent CLIs")
        return 0 if not installed else 1

    targets_to_update: list[TargetAdapter] = []

    if target:
        target_names = [t.strip().lower() for t in target.split(",") if t.strip()]
        available = ", ".join(adapters.keys())
        for name in target_names:
            if name not in adapters:
                raise SwitchError(f"unknown agent '{name}', available: {available}")
            adp = adapters[name]
            if not adp.get_binary_path():
                print(
                    f"✖ Agent '{name}' is not installed. "
                    f"Run 'xpx agent install {name}' first.",
                    file=sys.stderr,
                )
                return 1
            targets_to_update.append(adp)

        if len(targets_to_update) == 1:
            adp = targets_to_update[0]
            old_ver = adp.get_cli_version()
            ver_tag = f"[current: {old_ver or 'unknown'}]"
            print(f"⏳ Updating agent '{adp.name}' {ver_tag}...")
            ok, msg = adp.update(dry_run=dry_run)
            if ok:
                new_ver = adp.get_cli_version()
                ver_note = (
                    f" ({old_ver} -> {new_ver})"
                    if (not dry_run and new_ver and new_ver != old_ver)
                    else ""
                )
                print(f"✔ {msg}{ver_note}")
                return 0
            print(f"✖ Failed to update '{adp.name}': {msg}", file=sys.stderr)
            return 1
    else:
        # --all mode
        targets_to_update = [
            adapters[name]
            for name in ORDERED_AGENTS
            if name in adapters and adapters[name].get_binary_path()
        ]
        if not targets_to_update:
            print(
                "No agent CLIs are installed. "
                "Run 'xpx agent install --all' to install them."
            )
            return 0

    target_names_str = ", ".join(a.name for a in targets_to_update)
    print(
        f"Found {len(targets_to_update)} installed agent CLI(s) to update in parallel: "
        f"{target_names_str}\n"
    )

    failures: list[str] = []
    max_workers = min(len(targets_to_update), 5)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_update_single_agent, adp, dry_run): adp
            for adp in targets_to_update
        }
        for fut in as_completed(futures):
            name, display_name, ok, msg, old_ver, new_ver = fut.result()
            if ok:
                ver_note = (
                    f" ({old_ver} -> {new_ver})"
                    if (not dry_run and new_ver and new_ver != old_ver)
                    else ""
                )
                print(f"✔ [{name:<10}] {msg}{ver_note}")
            else:
                print(f"✖ [{name:<10}] {msg}", file=sys.stderr)
                failures.append(name)

    if failures:
        fail_list = ", ".join(failures)
        print(
            f"\nwarning: {len(failures)} agent(s) failed to update: {fail_list}",
            file=sys.stderr,
        )
        return 1

    print("\n✔ Successfully processed all requested agents.")
    return 0
