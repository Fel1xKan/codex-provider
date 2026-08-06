from __future__ import annotations

import json
import urllib.error
from typing import Any

import lib.cursor.db as db
import lib.cursor.oscrypt as oscrypt
import lib.cursor.store as st
from lib.common.cli import read_api_key
from lib.common.common_store import fsync_directory
from lib.common.errors import SwitchError
from lib.common.network import get_request_module, models_url, normalize_base_url
from lib.cursor.commands import _save_state_file


def _target_provider(provider_name: str | None):
    store = st.load_store()
    target = provider_name or store.current_provider
    if not target:
        raise SwitchError("no current provider; pass a provider name")
    if target not in store.providers:
        raise SwitchError(f"provider not found: {target}")
    return store.providers[target]


def _save_providers(
    store: st.StoreState,
    current_provider: str,
    providers: dict[str, Any],
    dry_run: bool,
) -> None:
    if dry_run:
        return
    st.state_dir().mkdir(parents=True, exist_ok=True)
    _save_state_file(
        store.current,
        st.accounts_data_dict(store),
        current_provider=current_provider,
        providers=providers,
    )
    fsync_directory(st.state_dir())


def provider_list_command() -> int:
    store = st.load_store()
    if not store.providers:
        print("no providers configured")
        return 0
    for name, prov in store.providers.items():
        marker = "*" if name == store.current_provider else " "
        key_state = "key set" if prov.api_key or prov.api_key_cipher else "no key"
        print(f"{marker} {name} ({prov.base_url}, {key_state})")
    return 0


def provider_add_command(
    name: str,
    from_current: bool = False,
    base_url: str | None = None,
    api_key_stdin: bool = False,
    dry_run: bool = False,
) -> int:
    if not st.PROVIDER_PATTERN.fullmatch(name):
        raise SwitchError(f"invalid provider name: {name}")

    current_base_url = db.read_openai_base_url()
    current_cipher = db.read_openai_key_cipher()

    if from_current:
        if not current_base_url and not current_cipher:
            raise SwitchError(
                "no custom provider configured in Cursor; "
                "add one in Settings > Models first"
            )
        base_url = current_base_url or base_url
        api_key_cipher = current_cipher
        api_key_plain = (
            oscrypt.decrypt_secret_buffer(current_cipher) if current_cipher else None
        )
    else:
        if not base_url:
            raise SwitchError("must pass --base-url or --from-current")
        base_url = normalize_base_url(base_url)
        api_key_cipher = ""
        api_key_plain = read_api_key(api_key_stdin)

    if not base_url:
        raise SwitchError("provider needs a base URL")

    st.acquire_lock()
    try:
        store = st.load_store()
        providers = st.providers_data_dict(store)
        existing = providers.get(name, {})
        models = existing.get("models", [])
        if not isinstance(models, list):
            models = []
        providers[name] = {
            "base_url": base_url,
            "api_key": api_key_plain or "",
            "api_key_cipher": api_key_cipher,
            "models": models,
        }
        if not dry_run:
            _save_providers(store, store.current_provider or name, providers, False)
    finally:
        st.release_lock()

    action = "would add" if dry_run else "added"
    key_state = (
        "with api key" if (api_key_plain or api_key_cipher) else "without api key"
    )
    print(f"{action} provider: {name} ({base_url}, {key_state})")
    return 0


def provider_switch_command(
    name: str, dry_run: bool = False, force: bool = False
) -> int:
    prov = _target_provider(name)
    if not prov.base_url:
        raise SwitchError(f"provider '{name}' has no base URL saved")

    if dry_run:
        print(f"would write provider: {name}")
        print(f"  would set openAIBaseUrl: {prov.base_url}")
        if prov.api_key or prov.api_key_cipher:
            print("  would set secret://cursorAuth/openAIKey")
        return 0

    from lib.cursor.commands import _ensure_cursor_quit

    _ensure_cursor_quit(force)

    cipher = prov.api_key_cipher
    if prov.api_key and not cipher:
        encrypted = oscrypt.encrypt_secret_plaintext(prov.api_key)
        if encrypted is None:
            raise SwitchError(
                f"unable to encrypt api key for provider '{name}'; "
                "run on Windows or capture the key in Cursor first "
                "(--from-current)"
            )
        cipher = encrypted

    db.write_openai_base_url(prov.base_url)
    db.write_openai_key_cipher(cipher)

    st.acquire_lock()
    try:
        store = st.load_store()
        _save_providers(store, name, st.providers_data_dict(store), False)
    finally:
        st.release_lock()

    print(f"switched provider: {name}")
    return 0


def provider_delete_command(
    name: str, full: bool = False, dry_run: bool = False, force: bool = False
) -> int:
    st.acquire_lock()
    try:
        store = st.load_store()
        if name not in store.providers:
            raise SwitchError(f"provider not found: {name}")
        current = store.current_provider
        if current == name:
            current = ""
        providers = st.providers_data_dict(store)
        providers.pop(name, None)
        if not dry_run:
            _save_providers(store, current, providers, False)
            if full:
                from lib.cursor.commands import _ensure_cursor_quit

                _ensure_cursor_quit(force)
                db.write_openai_base_url(None)
                db.write_openai_key_cipher(None)
    finally:
        st.release_lock()

    action = "would delete" if dry_run else "deleted"
    extra = " and clear provider config from Cursor" if full else ""
    print(f"{action} provider: {name}{extra}")
    return 0


def _fetch_model_ids(base_url: str, api_key: str, timeout: float) -> list[str]:
    endpoint = models_url(base_url)
    req_mod = get_request_module()
    req = req_mod.Request(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "cursor-provider",
            "Accept": "application/json",
        },
    )
    try:
        with req_mod.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SwitchError(f"models request failed: HTTP {exc.code}") from exc
    except Exception as exc:
        raise SwitchError(f"models request failed: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise SwitchError("response is not OpenAI-compatible (missing data array)")
    model_ids = [
        m["id"]
        for m in data["data"]
        if isinstance(m, dict) and isinstance(m.get("id"), str)
    ]
    if not model_ids:
        raise SwitchError("no models returned by the provider")
    return model_ids


def add_provider_parser(subparsers: Any) -> None:
    provider_parser = subparsers.add_parser(
        "provider", help="Manage custom OpenAI-compatible providers"
    )
    provider_sub = provider_parser.add_subparsers(
        dest="provider_command", required=True
    )

    provider_sub.add_parser("list", help="List configured providers")

    add_p = provider_sub.add_parser("add", help="Add a custom provider")
    add_p.add_argument("name", help="Provider name")
    add_p.add_argument(
        "--from-current",
        action="store_true",
        help="Capture the provider currently configured in Cursor",
    )
    add_p.add_argument("--base-url", help="OpenAI-compatible base URL")
    add_p.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="Read API key from stdin instead of a hidden interactive prompt",
    )
    add_p.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )

    switch_p = provider_sub.add_parser("switch", help="Switch the active provider")
    switch_p.add_argument("name", help="Provider name")
    switch_p.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )
    switch_p.add_argument(
        "--force",
        action="store_true",
        help="Write even when Cursor is running (may be overwritten)",
    )

    delete_p = provider_sub.add_parser("delete", help="Delete a provider")
    delete_p.add_argument("name", help="Provider name")
    delete_p.add_argument(
        "--full",
        action="store_true",
        help="Also clear the provider config in Cursor",
    )
    delete_p.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing files"
    )
    delete_p.add_argument(
        "--force",
        action="store_true",
        help="Write even when Cursor is running (may be overwritten)",
    )


def dispatch_provider(args: Any) -> int:
    if args.provider_command == "list":
        return provider_list_command()
    if args.provider_command == "add":
        return provider_add_command(
            args.name,
            from_current=args.from_current,
            base_url=args.base_url,
            api_key_stdin=args.api_key_stdin,
            dry_run=args.dry_run,
        )
    if args.provider_command == "switch":
        return provider_switch_command(args.name, args.dry_run, args.force)
    if args.provider_command == "delete":
        return provider_delete_command(args.name, args.full, args.dry_run, args.force)
    return 0
