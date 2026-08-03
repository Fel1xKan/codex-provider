from __future__ import annotations

import json
import sys
from contextlib import nullcontext
from pathlib import Path

import lib.codex.store as st
from lib.codex.switch import switch_provider
from lib.common.common_store import SECRET_FILE_MODE, atomic_write_bytes
from lib.common.errors import SwitchError
from lib.common.toml_config import render_tool_config, validate_provider_name


def export_command(file_path: str | None) -> int:
    state = st.ensure_provider_state(read_only=True)
    export_data = {
        "type": "codex-provider",
        "version": 1,
        "active_provider": state.active_provider,
        "providers": {},
    }

    for provider, pconfig in state.providers.items():
        auth_data = {}
        profile = st.auth_profile_path(provider)
        if profile.exists():
            try:
                from lib.codex.doctor import load_auth_json

                auth_data = load_auth_json(profile)
            except Exception:
                pass
        export_data["providers"][provider] = {"config": pconfig, "auth": auth_data}

    payload = json.dumps(export_data, indent=2, ensure_ascii=False) + "\n"
    if not file_path or file_path == "-":
        sys.stdout.write(payload)
    else:
        path = Path(file_path).expanduser()
        if path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(
            path, payload.encode("utf-8"), secret=True, mode=SECRET_FILE_MODE
        )
        print(f"exported Codex configuration and auth to {path}")
    return 0


def import_command(file_path: str | None, dry_run: bool) -> int:
    if not file_path or file_path == "-":
        try:
            raw_data = sys.stdin.read()
        except KeyboardInterrupt:
            return 1
    else:
        path = Path(file_path).expanduser()
        if not path.exists():
            raise SwitchError(f"import file not found: {path}")
        raw_data = path.read_text(encoding="utf-8")

    try:
        data = json.loads(raw_data)
    except Exception as exc:
        raise SwitchError(f"invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise SwitchError("imported data must be a JSON object")

    if data.get("type") != "codex-provider":
        t = data.get("type")
        raise SwitchError(
            f"invalid export file type: expected codex-provider, found {t}"
        )

    version = data.get("version")
    if version != 1:
        raise SwitchError(f"unsupported version: {version}")

    providers_to_import = data.get("providers")
    if not isinstance(providers_to_import, dict):
        raise SwitchError("providers must be a JSON object")

    lock = nullcontext() if dry_run else st.state_lock()
    with lock:
        state = st.ensure_provider_state(read_only=dry_run)
        providers = dict(state.providers)

        for provider, info in providers_to_import.items():
            provider = validate_provider_name(provider)
            if not isinstance(info, dict):
                raise SwitchError(f"invalid provider entry: {provider}")
            config = info.get("config")
            auth = info.get("auth")
            if not isinstance(config, dict) or not isinstance(auth, dict):
                raise SwitchError(
                    f"provider {provider} must have config and auth objects"
                )

            action = "would add/update" if dry_run else "added/updated"
            print(f"{action} provider: {provider}")

            if not dry_run:
                providers[provider] = config
                # Write auth snapshot
                profile = st.auth_profile_path(provider, create=True)
                auth_payload = (
                    json.dumps(auth, indent=2, ensure_ascii=False) + "\n"
                ).encode("utf-8")
                atomic_write_bytes(
                    profile, auth_payload, secret=True, mode=SECRET_FILE_MODE
                )

        if not dry_run:
            base_text = (
                st.tool_config_path().read_text(encoding="utf-8")
                if st.tool_config_path().exists()
                else None
            )
            updated = render_tool_config(
                state.codex_dir,
                providers,
                base_text=base_text,
                active_provider=state.active_provider,
            )
            atomic_write_bytes(
                st.tool_config_path(),
                updated.encode("utf-8"),
                secret=True,
                mode=SECRET_FILE_MODE,
            )

        active_provider = data.get("active_provider")
        if active_provider and (
            active_provider in providers_to_import or active_provider in state.providers
        ):
            if dry_run:
                print(f"would switch default provider: {active_provider}")
            else:
                switch_provider(active_provider, dry_run=False)

    return 0
