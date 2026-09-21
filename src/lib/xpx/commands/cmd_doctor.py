from __future__ import annotations

import os
import sys
from typing import Any

from lib.common.common_store import chmod_if_supported
from lib.common.constants import PRIVATE_DIR_MODE, SECRET_FILE_MODE
from lib.xpx.adapters.registry import detect_installed_adapters
from lib.xpx.store import ensure_xpx_dirs, get_xpx_home
from lib.xpx.store.account_store import AccountStore
from lib.xpx.store.provider_store import ProviderStore
from lib.xpx.store.state_store import StateStore


def run_doctor(args: Any) -> int:
    fix = getattr(args, "fix", False)
    issues: list[str] = []
    fixed: list[str] = []

    print("Running xpx system health check...\n")

    # 1. Directory and storage layout
    home = get_xpx_home()
    if not home.is_dir():
        issues.append(f"Storage directory missing: {home}")
        if fix:
            ensure_xpx_dirs()
            fixed.append(f"Created {home}")
    elif os.name == "posix":
        mode = home.stat().st_mode & 0o777
        if mode != PRIVATE_DIR_MODE:
            issues.append(
                f"Storage directory has insecure permissions: "
                f"{oct(mode)} (expected 0o700)"
            )
            if fix:
                chmod_if_supported(home, PRIVATE_DIR_MODE)
                fixed.append(f"Fixed permissions on {home}")

    # 2. Check provider credentials
    pv_store = ProviderStore()
    providers = pv_store.list_all()
    print(f"Checking {len(providers)} configured provider(s)...")
    for p in providers:
        p_path = pv_store.provider_path(p.name)
        if os.name == "posix":
            mode = p_path.stat().st_mode & 0o777
            if mode != SECRET_FILE_MODE:
                issues.append(
                    f"Provider file '{p.name}.json' has insecure "
                    f"permissions: {oct(mode)} (expected 0o600)"
                )
                if fix:
                    chmod_if_supported(p_path, SECRET_FILE_MODE)
                    fixed.append(f"Fixed permissions on {p_path.name}")
        if not p.base_url:
            issues.append(f"Provider '{p.name}' is missing base_url")
        if not p.api_key:
            issues.append(f"Provider '{p.name}' has empty API key")

    # 3. Check target client configuration readability
    installed = detect_installed_adapters()
    print(f"Checking {len(installed)} detected target client(s)...")
    for t_name, adp in installed.items():
        st = adp.get_status()
        if st.active_type == "error":
            issues.append(f"Target '{t_name}' config error: {st.active_name}")

    # 4. Check global state consistency
    state_store = StateStore()
    state = state_store.load()
    acc_store = AccountStore()
    dangling: list[str] = []
    for t_name, ts in state.targets.items():
        if ts.active_type == "provider" and not pv_store.exists(ts.active_name):
            issues.append(
                f"State points to non-existent provider '{ts.active_name}' "
                f"for target '{t_name}'"
            )
            dangling.append(t_name)
        elif ts.active_type == "account" and not acc_store.exists(
            t_name, ts.active_name
        ):
            issues.append(
                f"State points to non-existent account '{ts.active_name}' "
                f"for target '{t_name}'"
            )
            dangling.append(t_name)

    if fix and dangling:
        for t in dangling:
            state_store.remove_target_state(t)
            fixed.append(f"Removed dangling state for target '{t}'")

    print("")
    if fixed:
        print("Fixed issues:")
        for f in fixed:
            print(f"  ✔ {f}")
        print("")

    if issues and not fix:
        print("Issues detected:")
        for issue in issues:
            print(f"  ✖ {issue}")
        print("\nRun 'xpx doctor --fix' to automatically resolve fixable issues.")
        return 1

    if issues and fix:
        remaining = len(issues) - len(fixed)
        if remaining > 0:
            print(
                f"Doctor completed with {remaining} unresolved issue(s).",
                file=sys.stderr,
            )
            return 1
        print("✔ All issues resolved.")
        return 0

    print("✔ No issues detected. Everything is healthy.")
    return 0
