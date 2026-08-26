from __future__ import annotations

import json
from contextlib import nullcontext, suppress
from pathlib import Path
from typing import Any

import lib.codex.store as st
from lib.common.common_store import (
    FileChange,
    apply_changes,
    atomic_write_bytes,
)
from lib.common.constants import RUNTIME_PROVIDER_ID, SECRET_FILE_MODE
from lib.common.errors import SwitchError
from lib.common.recent import (
    load_recent_providers,
    serialize_recent_providers,
)
from lib.common.toml_config import (
    render_runtime_config,
    render_tool_config,
    validate_provider_name,
)

commit_file_changes = apply_changes


def render_tool_state(
    state: st.ProviderState,
    providers: dict[str, dict[str, Any]],
    active_provider: str,
) -> bytes:
    base_text = (
        st.tool_config_path().read_text(encoding="utf-8")
        if st.tool_config_path().exists()
        else None
    )
    return render_tool_config(
        state.codex_dir,
        providers,
        base_text=base_text,
        active_provider=active_provider,
    ).encode("utf-8")


def migrate_runtime_config(
    cfg_path: Path, codex_dir: Path, active: str, providers: dict[str, dict[str, Any]]
) -> None:
    r_config = st.runtime_config_path(codex_dir)
    if not r_config.exists() or active not in providers:
        return
    with suppress(Exception):
        r_text = r_config.read_text(encoding="utf-8")
        try:
            r_data = st.parse_toml(r_config)
            needs_mig = r_data.get("model_provider") != RUNTIME_PROVIDER_ID or set(
                r_data.get("model_providers", {}).keys()
            ) != {RUNTIME_PROVIDER_ID}
        except Exception:
            needs_mig = True

        if needs_mig:
            atomic_write_bytes(
                r_config,
                render_runtime_config(r_text, providers[active]).encode("utf-8"),
            )
            t_text = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else None
            updated_t = render_tool_config(
                codex_dir, providers, base_text=t_text, active_provider=active
            )
            atomic_write_bytes(
                cfg_path, updated_t.encode("utf-8"), secret=True, mode=SECRET_FILE_MODE
            )


def switch_provider(provider: str, dry_run: bool) -> int:
    provider = validate_provider_name(provider)
    lock = nullcontext() if dry_run else st.state_lock()
    with lock:
        state = st.ensure_provider_state(read_only=dry_run)
        current = state.active_provider
        providers = state.providers
        if provider not in providers:
            known = ", ".join(sorted(providers.keys()))
            raise SwitchError(f"unknown provider '{provider}', available: {known}")

        target_auth = st.auth_profile_path(provider, create=not dry_run)
        if not target_auth.exists():
            raise SwitchError(
                f"auth profile is missing for provider '{provider}': {target_auth}"
            )
        try:
            payload = json.loads(target_auth.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SwitchError(
                f"invalid auth JSON for provider '{provider}': {target_auth}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise SwitchError(
                f"auth profile for '{provider}' must contain an object: {target_auth}"
            )

        runtime_config = st.runtime_config_path(state.codex_dir, create=not dry_run)
        runtime_auth = st.runtime_auth_path(state.codex_dir, create=not dry_run)
        base_text = (
            runtime_config.read_text(encoding="utf-8")
            if runtime_config.exists()
            else f'model_provider = "{RUNTIME_PROVIDER_ID}"\n'
        )

        runtime_payload = render_runtime_config(base_text, providers[provider]).encode(
            "utf-8"
        )
        tool_payload = render_tool_state(state, providers, active_provider=provider)

        changes = [
            FileChange(st.tool_config_path(), tool_payload, secret=True),
        ]
        if current != provider or not runtime_auth.exists():
            changes.append(
                FileChange(runtime_auth, target_auth.read_bytes(), secret=True)
            )
        changes.append(FileChange(runtime_config, runtime_payload))
        recent_record = [provider] + [
            name for name in load_recent_providers(st.recent_path()) if name != provider
        ]
        changes.append(
            FileChange(
                st.recent_path(),
                serialize_recent_providers(recent_record),
                secret=True,
            )
        )

        if not dry_run:
            commit_file_changes(changes)

    action = "would switch" if dry_run else "switched"
    print(f"{action} default provider: {provider}")
    return 0
