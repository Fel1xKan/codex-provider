from __future__ import annotations

from typing import Any

from lib.xpx.adapters.registry import get_all_adapters
from lib.xpx.store.state_store import StateStore


def run_status(args: Any) -> int:
    adapters = get_all_adapters()
    state_store = StateStore()
    global_state = state_store.load()

    header = (
        f"{'Target':<12} {'Type':<10} {'Active Source':<18} "
        f"{'Active Model':<20} {'Status':<18}"
    )
    print(header)
    print("-" * 78)

    for name in ("codex", "pi", "opencode", "cursor", "claude", "agy"):
        if name not in adapters:
            continue
        adp = adapters[name]
        tstatus = adp.get_status()
        recorded = global_state.targets.get(name)

        target_col = name
        type_col = tstatus.active_type
        source_col = tstatus.active_name
        model_col = tstatus.active_model or "-"

        # Fallback to recorded state if native file doesn't detail provider name
        if recorded and tstatus.active_type == "provider":
            if source_col.startswith("http") or source_col == "custom":
                source_col = recorded.active_name
            if model_col == "-" and recorded.active_model:
                model_col = recorded.active_model

        if not tstatus.installed:
            status_col = "- Not installed"
            type_col = "none"
            source_col = "-"
            model_col = "-"
        elif tstatus.active_type == "provider":
            fast_info = f" ({tstatus.extra_summary})" if tstatus.extra_summary else ""
            status_col = f"● Active{fast_info}"
        elif tstatus.active_type == "account":
            status_col = "● Active"
        elif tstatus.active_type == "official":
            status_col = "○ Default"
            source_col = "-"
        else:
            status_col = "○ Inactive"
            source_col = "-"
            model_col = "-"

        print(
            f"{target_col:<12} {type_col:<10} {source_col:<18} "
            f"{model_col:<20} {status_col:<18}"
        )

    return 0
