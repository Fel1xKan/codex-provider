from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Any

import json5
import tomlkit

from lib.common.errors import SwitchError
from lib.xpx.commands.legacy import DiscoveredItem, StateMap
from lib.xpx.commands.legacy import collect_legacy_items as _collect_legacy
from lib.xpx.store.account_store import AccountSpec, AccountStore
from lib.xpx.store.provider_store import (
    ProviderSpec,
    ProviderStore,
    TargetOverrides,
)
from lib.xpx.store.state_store import StateStore

WELL_KNOWN_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "302ai": "https://api.302.ai/v1",
}


def _active_name(cur_ts: Any) -> str | None:
    """Name of the target's active state, or None when nothing is active."""
    if cur_ts is None or cur_ts.active_type in (None, "none"):
        return None
    return str(cur_ts.active_name)


def sniff_and_import_file(path: Path) -> int:
    if not path.is_file():
        raise SwitchError(f"file not found: {path}")

    content = path.read_text(encoding="utf-8")
    pv_store = ProviderStore()
    acc_store = AccountStore()
    count = 0

    # 1. Full xpx backup
    if '"version"' in content and '"providers"' in content:
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "providers" in data:
                for p_dict in data["providers"]:
                    spec = ProviderSpec.from_dict(p_dict)
                    pv_store.save(spec)
                    count += 1
                if "accounts" in data and isinstance(data["accounts"], list):
                    for a_dict in data["accounts"]:
                        acc = AccountSpec.from_dict(a_dict)
                        acc_store.save(acc)
                        count += 1
                print(f"✔ Imported {count} item(s) from xpx backup {path.name}.")
                return 0
        except Exception:
            pass

    # 2. Codex TOML config
    if "[model_providers" in content or "model_providers." in content:
        try:
            doc = tomlkit.parse(content)
            providers = doc.get("model_providers", {})
            for name, cfg in providers.items():
                if isinstance(cfg, dict) and "base_url" in cfg:
                    spec = ProviderSpec(
                        name=name,
                        base_url=cfg["base_url"],
                        api_key=cfg.get("api_key", ""),
                        targets={
                            "codex": TargetOverrides(
                                wire_api=cfg.get("wire_api"),
                                headers=dict(cfg.get("http_headers") or {}),
                            )
                        },
                    )
                    pv_store.save(spec)
                    count += 1
            print(f"✔ Imported {count} provider(s) from Codex TOML config.")
            return 0
        except Exception as exc:
            raise SwitchError(f"failed to parse Codex TOML: {exc}") from exc

    # 3. OpenCode JSON
    if '"options"' in content and ('"baseURL"' in content or '"apiKey"' in content):
        try:
            data = json5.loads(content)
            prov_dict = data.get("provider") if isinstance(data, dict) else {}
            if isinstance(prov_dict, dict):
                for name, cfg in prov_dict.items():
                    options = cfg.get("options", {}) if isinstance(cfg, dict) else {}
                    burl = options.get("baseURL") or options.get("base_url")
                    if burl:
                        spec = ProviderSpec(
                            name=name,
                            base_url=burl,
                            api_key=options.get("apiKey", ""),
                        )
                        pv_store.save(spec)
                        count += 1
                print(f"✔ Imported {count} provider(s) from OpenCode config.")
                return 0
        except Exception:
            pass

    # 4. Claude settings
    if "ANTHROPIC_BASE_URL" in content:
        try:
            data = json.loads(content)
            env = data.get("env", {}) if isinstance(data, dict) else {}
            base_url = env.get("ANTHROPIC_BASE_URL")
            token = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY", "")
            if base_url:
                spec = ProviderSpec(
                    name="claude-imported",
                    base_url=base_url,
                    api_key=token,
                    protocol="anthropic",
                    default_model=env.get("ANTHROPIC_MODEL"),
                )
                pv_store.save(spec)
                count += 1
                print("✔ Imported 1 provider from Claude settings.")
                return 0
        except Exception:
            pass

    raise SwitchError(f"unable to recognize format of {path}")


def collect_legacy_items() -> tuple[list[DiscoveredItem], StateMap]:
    """Scan local machine and collect configurations from all 6 tools."""
    return _collect_legacy()


def scan_and_migrate_all(
    dry_run: bool = False,
    quiet: bool = False,
    force: bool = False,
) -> int:
    """Migrate all legacy and native configurations into ~/.xpx/."""
    if not quiet:
        print(
            "Scanning system for agent configurations "
            "(Codex, OpenCode, Claude, Cursor, Antigravity, Pi)..."
        )

    items, active_states = collect_legacy_items()
    if not items and not active_states:
        if not quiet:
            print("No legacy configurations found.")
        return 0

    pv_store = ProviderStore()
    acc_store = AccountStore()
    state_store = StateStore()

    if dry_run:
        print("\nDiscovered legacy configurations (dry-run):")
        # Group by source
        grouped: dict[str, list[DiscoveredItem]] = {}
        for it in items:
            grouped.setdefault(it.source_label, []).append(it)

        for src, src_items in sorted(grouped.items()):
            print(f"\n  [{src}]")
            for it in src_items:
                kind = "Provider" if it.item_type == "provider" else "Account"
                exists = (
                    pv_store.exists(it.name)
                    if it.item_type == "provider"
                    else acc_store.exists(getattr(it.payload, "target", ""), it.name)
                )
                status = ""
                if exists:
                    status = " [will overwrite]" if force else " [exists - skip/merge]"
                print(f"    • {kind}: {it.name} ({it.summary}){status}")

        if active_states:
            print("\nActive Target States (dry-run):")
            for target, (a_type, a_name, a_model) in sorted(active_states.items()):
                m_str = f" (model: {a_model})" if a_model else ""
                cur_ts = state_store.get_target_state(target)
                active = _active_name(cur_ts)
                status = ""
                if active is not None and active != a_name:
                    status = (
                        f" [will overwrite active '{active}']"
                        if force
                        else f" [kept active '{active}']"
                    )
                print(f"    • {target}: {a_type} '{a_name}'{m_str}{status}")

        n_items = len(items)
        n_src = len(grouped)
        print(
            f"\n[dry-run] Found {n_items} legacy item(s) across {n_src} source(s). "
            "No changes written."
        )
        return len(items)

    # Perform real migration
    count = 0
    migrated_sources = set()

    for it in items:
        if it.item_type == "provider":
            spec: ProviderSpec = it.payload  # type: ignore[assignment]
            if pv_store.exists(spec.name):
                if force:
                    pv_store.save(spec)
                    count += 1
                    migrated_sources.add(it.source_label)
                    if not quiet:
                        print(
                            f"  ✔ Overwrote provider '{spec.name}' "
                            f"from {it.source_label} (--force)"
                        )
                else:
                    # Merge if missing API key or targets
                    existing = pv_store.require(spec.name)
                    modified = False
                    if not existing.api_key and spec.api_key:
                        existing.api_key = spec.api_key
                        modified = True
                    if spec.targets:
                        for t_name, t_overrides in spec.targets.items():
                            if t_name not in existing.targets:
                                existing.targets[t_name] = t_overrides
                                modified = True
                    if modified:
                        pv_store.save(existing)
                        count += 1
                        migrated_sources.add(it.source_label)
                        if not quiet:
                            print(f"  ✔ Updated '{spec.name}' from {it.source_label}")
                    elif not quiet:
                        print(
                            f"  • Skipped existing provider '{spec.name}' "
                            "(use --force to overwrite)"
                        )
            else:
                pv_store.save(spec)
                count += 1
                migrated_sources.add(it.source_label)
                if not quiet:
                    print(f"  ✔ Imported provider '{spec.name}' from {it.source_label}")

        elif it.item_type == "account":
            acc: AccountSpec = it.payload  # type: ignore[assignment]
            if acc_store.exists(acc.target, acc.name):
                if force:
                    acc_store.save(acc)
                    count += 1
                    migrated_sources.add(it.source_label)
                    if not quiet:
                        email_val = acc.metadata.get("email")
                        email_str = f" ({email_val})" if email_val else ""
                        print(
                            f"  ✔ Overwrote {acc.target} account '{acc.name}'"
                            f"{email_str} (--force)"
                        )
                elif not quiet:
                    print(
                        f"  • Skipped existing {acc.target} account '{acc.name}' "
                        "(use --force to overwrite)"
                    )
            else:
                acc_store.save(acc)
                count += 1
                migrated_sources.add(it.source_label)
                if not quiet:
                    email_val = acc.metadata.get("email")
                    email_str = f" ({email_val})" if email_val else ""
                    print(f"  ✔ Imported {acc.target} account '{acc.name}'{email_str}")

    # Save active target states into StateStore
    for target, (a_type, a_name, a_model) in sorted(active_states.items()):
        cur_ts = state_store.get_target_state(target)
        active = _active_name(cur_ts)
        if active is not None and not force and active != a_name:
            if not quiet:
                print(
                    f"  • Kept active state for {target} "
                    f"('{active}', use --force to overwrite)"
                )
            continue
        state_store.set_target_state(target, a_type, a_name, a_model)
        if not quiet:
            m_str = f"/{a_model}" if a_model else ""
            tag = (
                " (--force)"
                if (active is not None and force and active != a_name)
                else ""
            )
            print(
                f"  ✔ Recorded active state for {target}: "
                f"{a_type} '{a_name}{m_str}'{tag}"
            )

    from lib.xpx.store import xpx_home

    with contextlib.suppress(Exception):
        (xpx_home() / ".migrated").touch()

    if not quiet:
        print(f"\n✔ Migration complete. Imported {count} item(s).")
    elif count > 0:
        for src in sorted(migrated_sources):
            print(f"Migrated legacy config from {src} to ~/.xpx/", file=sys.stderr)

    return count


def auto_migrate_legacy_if_needed() -> None:
    """Detect legacy configs on first run and auto-import them into ~/.xpx/."""
    from lib.xpx.store import xpx_home

    migrated_marker = xpx_home() / ".migrated"
    if migrated_marker.exists():
        return

    # Check if this is the first time running
    pv_store = ProviderStore()
    acc_store = AccountStore()
    if pv_store.list_all() or acc_store.list_all():
        with contextlib.suppress(Exception):
            migrated_marker.touch()
        return

    with contextlib.suppress(Exception):
        scan_and_migrate_all(dry_run=False, quiet=True)
        migrated_marker.touch()


def run_migrate(args: Any) -> int:
    dry_run = getattr(args, "dry_run", False)
    force = getattr(args, "force", False)
    scan_and_migrate_all(dry_run=dry_run, quiet=False, force=force)
    return 0


def run_import(args: Any) -> int:
    file_arg = getattr(args, "file", None)
    force = getattr(args, "force", False)
    if file_arg:
        return sniff_and_import_file(Path(file_arg))

    print("Tip: Run 'xpx migrate' to scan and migrate legacy configurations.\n")
    scan_and_migrate_all(dry_run=False, quiet=False, force=force)
    return 0


def run_export(args: Any) -> int:
    file_arg = getattr(args, "file", None)
    pv_store = ProviderStore()
    acc_store = AccountStore()
    state_store = StateStore()

    data = {
        "version": 1,
        "providers": [p.to_dict() for p in pv_store.list_all()],
        "accounts": [a.to_dict() for a in acc_store.list_all()],
        "state": state_store.load().to_dict(),
    }
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    if not file_arg or file_arg == "-":
        print(payload)
        return 0

    dest = Path(file_arg)
    dest.write_text(payload, encoding="utf-8")
    p_count = len(data["providers"])
    a_count = len(data["accounts"])
    print(f"✔ Exported {p_count} provider(s) and {a_count} account(s) to {dest}.")
    return 0
