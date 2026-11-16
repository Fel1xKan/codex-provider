"""Collect accounts from the native Antigravity state files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.common.jwt_helper import parse_jwt_claims
from lib.xpx.adapters.agy import get_agy_cli_dir
from lib.xpx.store.account_store import AccountSpec

from .common import DiscoveredItem, StateMap

_LABEL = "Antigravity (apx)"


def collect(items: list[DiscoveredItem], states: StateMap, home: Path) -> None:
    """Antigravity (apx & native) configurations."""
    agy_dir = home / ".gemini" / "agy-provider"
    _collect_state(items, states, agy_dir / "state" / "state.json")
    _collect_auth(items, agy_dir / "auth.json")
    _collect_native(items, states, get_agy_cli_dir() / "antigravity-oauth-token")


def _has_agy_account(items: list[DiscoveredItem], name: str) -> bool:
    return any(
        it.item_type == "account"
        and isinstance(it.payload, AccountSpec)
        and it.payload.target == "agy"
        and it.name == name
        for it in items
    )


def _add_account(
    items: list[DiscoveredItem],
    name: str,
    token_data: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    spec = AccountSpec(
        target="agy",
        name=name,
        account_type="google-oauth",
        token_data=token_data,
        metadata=metadata,
    )
    items.append(
        DiscoveredItem(
            source_label=_LABEL,
            item_type="account",
            name=name,
            summary=f"target=agy, email={metadata.get('email') or '-'}",
            payload=spec,
        )
    )


def _collect_state(items: list[DiscoveredItem], states: StateMap, path: Path) -> None:
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    current = data.get("current")
    if current:
        states["agy"] = ("account", current, None)
    for acc_name, acc_info in data.get("accounts", {}).items():
        if not isinstance(acc_info, dict):
            continue
        token_data = acc_info.get("token_data")
        _add_account(
            items,
            acc_name,
            token_data if isinstance(token_data, dict) else {},
            {
                "email": acc_info.get("email", ""),
                "display_name": acc_info.get("display_name", ""),
            },
        )


def _collect_auth(items: list[DiscoveredItem], path: Path) -> None:
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    for acc_name, acc_info in data.items():
        if _has_agy_account(items, acc_name):
            continue
        token_data = acc_info if isinstance(acc_info, dict) else {}
        _add_account(items, acc_name, token_data, {})


def _collect_native(items: list[DiscoveredItem], states: StateMap, path: Path) -> None:
    if not path.is_file():
        return
    try:
        token_data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(token_data, dict):
        return
    id_token = token_data.get("id_token")
    claims = (parse_jwt_claims(id_token) or {}) if id_token else {}
    email = claims.get("email", "")
    name = claims.get("name", "")
    acc_name = _account_name_for(items, email)
    if not _has_agy_account(items, acc_name):
        _add_account(
            items, acc_name, token_data, {"email": email, "display_name": name}
        )
    states.setdefault("agy", ("account", acc_name, None))


def _account_name_for(items: list[DiscoveredItem], email: str) -> str:
    for it in items:
        if (
            it.item_type == "account"
            and isinstance(it.payload, AccountSpec)
            and it.payload.target == "agy"
            and it.payload.metadata.get("email") == email
        ):
            return it.name
    if not email:
        return "default"
    prefix = email.split("@")[0].lower()
    return "".join(c for c in prefix if c.isalnum() or c in ("-", "_")) or "default"
