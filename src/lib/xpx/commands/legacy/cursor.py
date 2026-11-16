"""Collect accounts and providers from the native Cursor database."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path

from lib.xpx.adapters.cursor import get_cursor_db_path
from lib.xpx.store.account_store import AccountSpec
from lib.xpx.store.provider_store import ProviderSpec

from .common import DiscoveredItem, StateMap


def collect(items: list[DiscoveredItem], states: StateMap, home: Path) -> None:
    """Cursor (cupx & native) configurations."""
    cursor_dir = home / ".cursor-provider"
    _collect_legacy_state(items, states, cursor_dir)
    _collect_legacy_auth(items, states, cursor_dir)
    _collect_native(items, states)


def _collect_legacy_state(
    items: list[DiscoveredItem], states: StateMap, cursor_dir: Path
) -> None:
    """Collect accounts from the legacy ~/.cursor-provider state file."""
    cursor_state = cursor_dir / "state" / "state.json"
    if cursor_state.is_file():
        try:
            cdata = json.loads(cursor_state.read_text(encoding="utf-8"))
            if isinstance(cdata, dict):
                curr = cdata.get("current")
                if curr:
                    states["cursor"] = ("provider", curr, None)

                # Providers
                for name, pinfo in cdata.get("providers", {}).items():
                    if isinstance(pinfo, dict) and pinfo.get("base_url"):
                        models = pinfo.get("models", [])
                        def_model = models[0] if models else None
                        spec = ProviderSpec(
                            name=name,
                            base_url=pinfo["base_url"],
                            api_key=pinfo.get("api_key", ""),
                            protocol="openai",
                            default_model=def_model,
                        )
                        has_key = "yes" if spec.api_key else "no"
                        items.append(
                            DiscoveredItem(
                                source_label="Cursor (cupx)",
                                item_type="provider",
                                name=name,
                                summary=f"url={spec.base_url}, key={has_key}",
                                payload=spec,
                            )
                        )
                # Accounts
                for acc_name, acc_info in cdata.get("accounts", {}).items():
                    if isinstance(acc_info, dict):
                        auth_data = acc_info.get("auth_data", {})
                        email = acc_info.get("email", "")
                        disp = acc_info.get("display_name", "")
                        acc = AccountSpec(
                            target="cursor",
                            name=acc_name,
                            account_type="cursor-auth",
                            token_data=auth_data if isinstance(auth_data, dict) else {},
                            metadata={"email": email, "display_name": disp},
                        )
                        items.append(
                            DiscoveredItem(
                                source_label="Cursor (cupx)",
                                item_type="account",
                                name=acc_name,
                                summary=f"target=cursor, email={email or '-'}",
                                payload=acc,
                            )
                        )
        except Exception:
            pass


def _collect_legacy_auth(
    items: list[DiscoveredItem], states: StateMap, cursor_dir: Path
) -> None:
    """Collect accounts from the legacy ~/.cursor-provider auth file."""
    cursor_auth = cursor_dir / "auth.json"
    if cursor_auth.is_file():
        with contextlib.suppress(Exception):
            cauth = json.loads(cursor_auth.read_text(encoding="utf-8"))
            if isinstance(cauth, dict):
                for acc_name, acc_info in cauth.items():
                    if not any(
                        it.name == acc_name
                        and isinstance(it.payload, AccountSpec)
                        and it.payload.target == "cursor"
                        for it in items
                        if it.item_type == "account"
                    ):
                        acc = AccountSpec(
                            target="cursor",
                            name=acc_name,
                            account_type="cursor-auth",
                            token_data=acc_info if isinstance(acc_info, dict) else {},
                            metadata={},
                        )
                        items.append(
                            DiscoveredItem(
                                source_label="Cursor (cupx)",
                                item_type="account",
                                name=acc_name,
                                summary="target=cursor",
                                payload=acc,
                            )
                        )


def _collect_native(items: list[DiscoveredItem], states: StateMap) -> None:
    """Collect the provider or account described by the native Cursor database."""
    native_cursor_db = get_cursor_db_path()
    if not native_cursor_db.is_file():
        return

    rows: dict[str, object] = {}
    try:
        con = sqlite3.connect(f"file:{native_cursor_db}?mode=ro", uri=True)
        try:
            rows = dict(
                con.execute(
                    "SELECT key, value FROM ItemTable WHERE key IN "
                    "('applicationUser', 'cursorAuth/cachedEmail', "
                    "'secret://cursorAuth/openAIKey', 'openaiApiKey')"
                ).fetchall()
            )
        finally:
            con.close()
    except Exception:
        return

    base_url = None
    model = None
    app_user_raw = rows.get("applicationUser")
    with contextlib.suppress(Exception):
        app_user = json.loads(str(app_user_raw)) if app_user_raw else None
        if isinstance(app_user, dict):
            base_url = app_user.get("openAIBaseUrl")
            composer = (
                app_user.get("aiSettings", {})
                .get("modelConfig", {})
                .get("composer", {})
            )
            model = composer.get("modelName") or composer.get("modelId")

    api_key_raw = rows.get("secret://cursorAuth/openAIKey") or rows.get("openaiApiKey")
    if base_url:
        _apply_native_provider(items, states, str(base_url), api_key_raw, model)
        return

    cached_email_raw = rows.get("cursorAuth/cachedEmail")
    if cached_email_raw:
        _apply_native_account(items, states, cached_email_raw)
        return

    if "cursor" not in states:
        states["cursor"] = ("official", "cursor", str(model) if model else None)


def _apply_native_provider(
    items: list[DiscoveredItem],
    states: StateMap,
    base_url: str,
    api_key_raw: object,
    model: object,
) -> None:
    matched_name = "cursor-custom"
    for it in items:
        if it.item_type == "provider" and isinstance(it.payload, ProviderSpec):
            u1 = it.payload.base_url.rstrip("/")
            u2 = base_url.rstrip("/")
            if u1 == u2 or u1.startswith(u2) or u2.startswith(u1):
                matched_name = it.name
                break
    if not any(it.name == matched_name for it in items):
        spec = ProviderSpec(
            name=matched_name,
            base_url=base_url,
            api_key=str(api_key_raw or ""),
            protocol="openai",
            default_model=str(model) if model else None,
        )
        items.append(
            DiscoveredItem(
                source_label="Cursor (cupx)",
                item_type="provider",
                name=matched_name,
                summary=f"url={spec.base_url}",
                payload=spec,
            )
        )
    states["cursor"] = ("provider", matched_name, str(model) if model else None)


def _apply_native_account(
    items: list[DiscoveredItem], states: StateMap, cached_email_raw: object
) -> None:
    email_str = str(cached_email_raw).strip('"').strip()
    acc_name = email_str.split("@")[0].lower() if "@" in email_str else "cursor_user"
    clean_name = (
        "".join(c for c in acc_name if c.isalnum() or c in ("-", "_")) or "cursor_user"
    )
    if not any(
        it.name == clean_name
        and isinstance(it.payload, AccountSpec)
        and it.payload.target == "cursor"
        for it in items
        if it.item_type == "account"
    ):
        acc = AccountSpec(
            target="cursor",
            name=clean_name,
            account_type="cursor-auth",
            token_data={"email": email_str},
            metadata={"email": email_str},
        )
        items.append(
            DiscoveredItem(
                source_label="Cursor (cupx)",
                item_type="account",
                name=clean_name,
                summary=f"target=cursor, email={email_str}",
                payload=acc,
            )
        )
    if "cursor" not in states:
        states["cursor"] = ("account", clean_name, None)
