from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import json5
import tomlkit
import yaml

from lib.common.errors import SwitchError
from lib.common.jwt_helper import parse_jwt_claims
from lib.xpx.adapters.agy import get_agy_cli_dir
from lib.xpx.adapters.claude import get_claude_settings_path
from lib.xpx.adapters.codex import get_codex_home
from lib.xpx.adapters.cursor import get_cursor_db_path
from lib.xpx.adapters.pi import get_pi_config_file
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


@dataclass
class DiscoveredItem:
    source_label: str  # e.g. "Codex (cpx)"
    item_type: str  # "provider" or "account"
    name: str
    summary: str
    payload: ProviderSpec | AccountSpec


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


def collect_legacy_items() -> tuple[
    list[DiscoveredItem], dict[str, tuple[str, str, str | None]]
]:
    """Scan local machine and collect configurations from all 6 tools."""
    items: list[DiscoveredItem] = []
    active_target_states: dict[str, tuple[str, str, str | None]] = {}
    home = Path.home()

    # ---------------------------------------------------------
    # 1. Codex (cpx & native) configurations
    # ---------------------------------------------------------
    codex_dir = home / ".codex-provider"
    codex_cfg = codex_dir / "config.toml"
    if codex_cfg.is_file():
        try:
            doc = tomlkit.parse(codex_cfg.read_text(encoding="utf-8"))
            for name, cfg in doc.get("model_providers", {}).items():
                if isinstance(cfg, dict) and "base_url" in cfg:
                    auth_p = codex_dir / "auth" / f"{name}.json"
                    api_key = ""
                    if auth_p.is_file():
                        with contextlib.suppress(Exception):
                            auth_data = json.loads(auth_p.read_text(encoding="utf-8"))
                            api_key = auth_data.get("OPENAI_API_KEY", "")

                    wire_api = cfg.get("wire_api")
                    headers = dict(cfg.get("http_headers") or {})
                    spec = ProviderSpec(
                        name=name,
                        base_url=cfg["base_url"],
                        api_key=api_key,
                        protocol="openai",
                        targets={
                            "codex": TargetOverrides(wire_api=wire_api, headers=headers)
                        },
                    )
                    has_key = "yes" if api_key else "no"
                    items.append(
                        DiscoveredItem(
                            source_label="Codex (cpx)",
                            item_type="provider",
                            name=name,
                            summary=f"url={spec.base_url}, key={has_key}",
                            payload=spec,
                        )
                    )
        except Exception:
            pass

    # Native ~/.codex/config.toml & auth.json
    native_codex_home = get_codex_home()
    native_codex_cfg = native_codex_home / "config.toml"
    native_codex_auth = native_codex_home / "auth.json"
    if native_codex_cfg.is_file():
        try:
            doc = tomlkit.parse(native_codex_cfg.read_text(encoding="utf-8"))
            active_p = str(doc.get("model_provider") or "")
            active_m = doc.get("model")
            if active_p:
                if active_p == "openai":
                    active_target_states["codex"] = (
                        "official",
                        "openai",
                        str(active_m) if active_m else None,
                    )
                else:
                    active_target_states["codex"] = (
                        "provider",
                        active_p,
                        str(active_m) if active_m else None,
                    )

            for name, cfg in doc.get("model_providers", {}).items():
                if (
                    isinstance(cfg, dict)
                    and "base_url" in cfg
                    and name != "openai"
                    and not any(it.name == name for it in items)
                ):
                    api_key = ""
                    if native_codex_auth.is_file():
                        with contextlib.suppress(Exception):
                            ajson = json.loads(
                                native_codex_auth.read_text(encoding="utf-8")
                            )
                            if isinstance(ajson, dict):
                                api_key = ajson.get("OPENAI_API_KEY") or ajson.get(
                                    f"{name}_api_key", ""
                                )
                    headers = dict(cfg.get("http_headers") or {})
                    spec = ProviderSpec(
                        name=name,
                        base_url=cfg["base_url"],
                        api_key=api_key,
                        protocol="openai",
                        targets={
                            "codex": TargetOverrides(
                                wire_api=cfg.get("wire_api"),
                                headers=headers,
                            )
                        },
                    )
                    has_key = "yes" if api_key else "no"
                    items.append(
                        DiscoveredItem(
                            source_label="Codex (cpx)",
                            item_type="provider",
                            name=name,
                            summary=f"url={spec.base_url}, key={has_key}",
                            payload=spec,
                        )
                    )
        except Exception:
            pass

    # ---------------------------------------------------------
    # 2. OpenCode (opx & native) configurations
    # ---------------------------------------------------------
    opencode_cfg_dir = (
        Path(os.environ["OPENCODE_CONFIG_DIR"])
        if os.environ.get("OPENCODE_CONFIG_DIR")
        else Path(os.environ["XDG_CONFIG_HOME"]) / "opencode"
        if os.environ.get("XDG_CONFIG_HOME")
        else home / ".config" / "opencode"
    )
    opencode_data_dir = (
        Path(os.environ["OPENCODE_DATA_DIR"])
        if os.environ.get("OPENCODE_DATA_DIR")
        else Path(os.environ["XDG_DATA_HOME"]) / "opencode"
        if os.environ.get("XDG_DATA_HOME")
        else home / ".local" / "share" / "opencode"
    )

    auth_keys: dict[str, str] = {}
    opencode_auth = opencode_data_dir / "auth.json"
    if opencode_auth.is_file():
        with contextlib.suppress(Exception):
            auth_json = json.loads(opencode_auth.read_text(encoding="utf-8"))
            if isinstance(auth_json, dict):
                for k, v in auth_json.items():
                    if isinstance(v, dict) and (v.get("key") or v.get("apiKey")):
                        auth_keys[k] = v.get("key") or v.get("apiKey")

    for cand_name in (
        "opencode.json",
        "opencode.jsonc",
        "opencode.json5",
        "opencode.config.json",
        "opencode.config.jsonc",
    ):
        cfg_file = opencode_cfg_dir / cand_name
        if cfg_file.is_file():
            try:
                data = json5.loads(cfg_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    curr_model = data.get("model")
                    if curr_model and isinstance(curr_model, str) and "/" in curr_model:
                        sp, sm = curr_model.split("/", 1)
                        active_target_states["opencode"] = (
                            "provider",
                            sp.strip(),
                            sm.strip(),
                        )
                    elif data.get("default_provider"):
                        active_target_states["opencode"] = (
                            "provider",
                            str(data["default_provider"]).strip(),
                            None,
                        )

                    providers_dict = data.get("provider", {})
                    if isinstance(providers_dict, dict):
                        for name, pcfg in providers_dict.items():
                            if not isinstance(pcfg, dict):
                                continue
                            opts = (
                                pcfg.get("options", {})
                                if isinstance(pcfg.get("options"), dict)
                                else {}
                            )
                            burl = opts.get("baseURL") or opts.get("base_url")
                            if not burl:
                                continue
                            api_key = opts.get("apiKey") or auth_keys.get(name, "")
                            models = pcfg.get("models", {})
                            default_model = None
                            if (
                                data.get("model")
                                and isinstance(data["model"], str)
                                and "/" in data["model"]
                            ):
                                sp, sm = data["model"].split("/", 1)
                                if sp == name:
                                    default_model = sm
                            elif isinstance(models, dict) and models:
                                default_model = next(iter(models.keys()))

                            spec = ProviderSpec(
                                name=name,
                                base_url=burl,
                                api_key=api_key,
                                protocol="openai",
                                default_model=default_model,
                            )
                            has_k = "yes" if api_key else "no"
                            items.append(
                                DiscoveredItem(
                                    source_label="OpenCode (opx)",
                                    item_type="provider",
                                    name=name,
                                    summary=f"url={burl}, key={has_k}",
                                    payload=spec,
                                )
                            )
            except Exception:
                pass
            break

    # Add any remaining well-known providers from opencode auth.json
    for name, key in auth_keys.items():
        if name in WELL_KNOWN_BASE_URLS and not any(it.name == name for it in items):
            spec = ProviderSpec(
                name=name,
                base_url=WELL_KNOWN_BASE_URLS[name],
                api_key=key,
                protocol="openai",
            )
            items.append(
                DiscoveredItem(
                    source_label="OpenCode (opx)",
                    item_type="provider",
                    name=name,
                    summary=f"url={spec.base_url}, key=yes",
                    payload=spec,
                )
            )

    # ---------------------------------------------------------
    # 3. Claude (clpx & native) configurations
    # ---------------------------------------------------------
    claude_dir = home / ".claude-provider"
    claude_cfg = claude_dir / "config.json"
    if claude_cfg.is_file():
        try:
            cdata = json.loads(claude_cfg.read_text(encoding="utf-8"))
            providers = cdata.get("providers", {}) if isinstance(cdata, dict) else {}
            for name, cfg in providers.items():
                if isinstance(cfg, dict):
                    auth_p = claude_dir / "auth" / f"{name}.json"
                    api_key = ""
                    if auth_p.is_file():
                        with contextlib.suppress(Exception):
                            auth_json = json.loads(auth_p.read_text(encoding="utf-8"))
                            api_key = auth_json.get(
                                "ANTHROPIC_AUTH_TOKEN"
                            ) or auth_json.get("ANTHROPIC_API_KEY", "")

                    spec = ProviderSpec(
                        name=name,
                        base_url=cfg.get("base_url", "https://api.anthropic.com"),
                        api_key=api_key,
                        protocol="anthropic",
                        default_model=cfg.get("model"),
                    )
                    has_key = "yes" if api_key else "no"
                    items.append(
                        DiscoveredItem(
                            source_label="Claude (clpx)",
                            item_type="provider",
                            name=name,
                            summary=f"url={spec.base_url}, key={has_key}",
                            payload=spec,
                        )
                    )
        except Exception:
            pass

    # Native ~/.claude/settings.json
    native_claude_path = get_claude_settings_path()
    if native_claude_path.is_file():
        try:
            sdata = json.loads(native_claude_path.read_text(encoding="utf-8"))
            env = sdata.get("env", {}) if isinstance(sdata, dict) else {}
            base_url = env.get("ANTHROPIC_BASE_URL")
            model = env.get("ANTHROPIC_MODEL")
            if base_url:
                token = env.get("ANTHROPIC_AUTH_TOKEN") or env.get(
                    "ANTHROPIC_API_KEY", ""
                )
                matched_name = "claude-custom"
                for it in items:
                    if it.item_type == "provider":
                        u1 = it.payload.base_url.rstrip("/")
                        u2 = str(base_url).rstrip("/")
                        if u1 == u2 or u1.startswith(u2) or u2.startswith(u1):
                            matched_name = it.name
                            break
                if not any(it.name == matched_name for it in items):
                    spec = ProviderSpec(
                        name=matched_name,
                        base_url=base_url,
                        api_key=token,
                        protocol="anthropic",
                        default_model=model,
                    )
                    items.append(
                        DiscoveredItem(
                            source_label="Claude (clpx)",
                            item_type="provider",
                            name=matched_name,
                            summary=f"url={base_url}",
                            payload=spec,
                        )
                    )
                active_target_states["claude"] = ("provider", matched_name, model)
            elif "claude" not in active_target_states:
                active_target_states["claude"] = ("official", "anthropic", model)
        except Exception:
            pass

    # ---------------------------------------------------------
    # 4. Cursor (cupx & native) configurations
    # ---------------------------------------------------------
    cursor_dir = home / ".cursor-provider"
    cursor_state = cursor_dir / "state" / "state.json"
    if cursor_state.is_file():
        try:
            cdata = json.loads(cursor_state.read_text(encoding="utf-8"))
            if isinstance(cdata, dict):
                curr = cdata.get("current")
                if curr:
                    active_target_states["cursor"] = ("provider", curr, None)

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

    cursor_auth = cursor_dir / "auth.json"
    if cursor_auth.is_file():
        with contextlib.suppress(Exception):
            cauth = json.loads(cursor_auth.read_text(encoding="utf-8"))
            if isinstance(cauth, dict):
                for acc_name, acc_info in cauth.items():
                    if not any(
                        it.name == acc_name and it.payload.target == "cursor"
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

    # Native Cursor state.vscdb
    native_cursor_db = get_cursor_db_path()
    if native_cursor_db.is_file():
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
                app_user_raw = rows.get("applicationUser")
                cached_email_raw = rows.get("cursorAuth/cachedEmail")
                api_key_raw = rows.get("secret://cursorAuth/openAIKey") or rows.get(
                    "openaiApiKey"
                )

                base_url = None
                model = None
                if app_user_raw:
                    with contextlib.suppress(Exception):
                        app_user = json.loads(app_user_raw)
                        base_url = app_user.get("openAIBaseUrl")
                        composer = (
                            app_user.get("aiSettings", {})
                            .get("modelConfig", {})
                            .get("composer", {})
                        )
                        model = composer.get("modelName") or composer.get("modelId")

                if base_url:
                    matched_name = "cursor-custom"
                    for it in items:
                        if it.item_type == "provider":
                            u1 = it.payload.base_url.rstrip("/")
                            u2 = str(base_url).rstrip("/")
                            if u1 == u2 or u1.startswith(u2) or u2.startswith(u1):
                                matched_name = it.name
                                break
                    if not any(it.name == matched_name for it in items):
                        spec = ProviderSpec(
                            name=matched_name,
                            base_url=str(base_url),
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
                    active_target_states["cursor"] = (
                        "provider",
                        matched_name,
                        str(model) if model else None,
                    )
                elif cached_email_raw:
                    email_str = cached_email_raw.strip('"').strip()
                    acc_name = (
                        email_str.split("@")[0].lower()
                        if "@" in email_str
                        else "cursor_user"
                    )
                    clean_name = (
                        "".join(c for c in acc_name if c.isalnum() or c in ("-", "_"))
                        or "cursor_user"
                    )
                    if not any(
                        it.name == clean_name and it.payload.target == "cursor"
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
                    if "cursor" not in active_target_states:
                        active_target_states["cursor"] = (
                            "account",
                            clean_name,
                            None,
                        )
                elif "cursor" not in active_target_states:
                    active_target_states["cursor"] = (
                        "official",
                        "cursor",
                        str(model) if model else None,
                    )
            finally:
                con.close()
        except Exception:
            pass

    # ---------------------------------------------------------
    # 5. Antigravity (apx & native) configurations
    # ---------------------------------------------------------
    agy_dir = home / ".gemini" / "agy-provider"
    agy_state = agy_dir / "state" / "state.json"
    if agy_state.is_file():
        try:
            adata = json.loads(agy_state.read_text(encoding="utf-8"))
            if isinstance(adata, dict):
                current_acc = adata.get("current")
                if current_acc:
                    active_target_states["agy"] = ("account", current_acc, None)

                for acc_name, acc_info in adata.get("accounts", {}).items():
                    if isinstance(acc_info, dict):
                        token_data = acc_info.get("token_data", {})
                        email = acc_info.get("email", "")
                        disp = acc_info.get("display_name", "")
                        acc = AccountSpec(
                            target="agy",
                            name=acc_name,
                            account_type="google-oauth",
                            token_data=token_data
                            if isinstance(token_data, dict)
                            else {},
                            metadata={"email": email, "display_name": disp},
                        )
                        items.append(
                            DiscoveredItem(
                                source_label="Antigravity (apx)",
                                item_type="account",
                                name=acc_name,
                                summary=f"target=agy, email={email or '-'}",
                                payload=acc,
                            )
                        )
        except Exception:
            pass

    agy_auth = agy_dir / "auth.json"
    if agy_auth.is_file():
        with contextlib.suppress(Exception):
            adata = json.loads(agy_auth.read_text(encoding="utf-8"))
            if isinstance(adata, dict):
                for acc_name, acc_info in adata.items():
                    if not any(
                        it.name == acc_name and it.payload.target == "agy"
                        for it in items
                        if it.item_type == "account"
                    ):
                        acc = AccountSpec(
                            target="agy",
                            name=acc_name,
                            account_type="google-oauth",
                            token_data=acc_info if isinstance(acc_info, dict) else {},
                            metadata={},
                        )
                        items.append(
                            DiscoveredItem(
                                source_label="Antigravity (apx)",
                                item_type="account",
                                name=acc_name,
                                summary="target=agy",
                                payload=acc,
                            )
                        )

    # Native Antigravity token: ~/.gemini/antigravity-cli/antigravity-oauth-token
    native_agy_token = get_agy_cli_dir() / "antigravity-oauth-token"
    if native_agy_token.is_file():
        try:
            tok_raw = native_agy_token.read_text(encoding="utf-8")
            tok_data = json.loads(tok_raw)
            if isinstance(tok_data, dict):
                id_token = tok_data.get("id_token")
                email = ""
                name = ""
                if id_token:
                    claims = parse_jwt_claims(id_token)
                    email = claims.get("email", "")
                    name = claims.get("name", "")

                acc_name = "default"
                if email:
                    prefix = email.split("@")[0].lower()
                    acc_name = (
                        "".join(c for c in prefix if c.isalnum() or c in ("-", "_"))
                        or "default"
                    )

                for it in items:
                    if (
                        it.item_type == "account"
                        and getattr(it.payload, "target", None) == "agy"
                        and it.payload.metadata.get("email") == email
                    ):
                        acc_name = it.name
                        break

                if not any(
                    it.name == acc_name and it.payload.target == "agy"
                    for it in items
                    if it.item_type == "account"
                ):
                    acc = AccountSpec(
                        target="agy",
                        name=acc_name,
                        account_type="google-oauth",
                        token_data=tok_data,
                        metadata={"email": email, "display_name": name},
                    )
                    items.append(
                        DiscoveredItem(
                            source_label="Antigravity (apx)",
                            item_type="account",
                            name=acc_name,
                            summary=f"target=agy, email={email or '-'}",
                            payload=acc,
                        )
                    )

                if "agy" not in active_target_states:
                    active_target_states["agy"] = ("account", acc_name, None)
        except Exception:
            pass

    # ---------------------------------------------------------
    # 6. Pi (native) configuration
    # ---------------------------------------------------------
    pi_cfg_path = get_pi_config_file()
    if pi_cfg_path.is_file():
        try:
            p_data = yaml.safe_load(pi_cfg_path.read_text(encoding="utf-8")) or {}
            pv = p_data.get("model_provider", {}) if isinstance(p_data, dict) else {}
            p_name = pv.get("name")
            p_base = pv.get("api_base")
            p_key = pv.get("api_key", "")
            p_model = pv.get("model")
            if p_name and p_base:
                spec = ProviderSpec(
                    name=str(p_name),
                    base_url=str(p_base),
                    api_key=str(p_key or ""),
                    protocol="openai",
                    default_model=str(p_model) if p_model else None,
                )
                if not any(it.name == str(p_name) for it in items):
                    items.append(
                        DiscoveredItem(
                            source_label="Pi (native)",
                            item_type="provider",
                            name=str(p_name),
                            summary=f"url={p_base}",
                            payload=spec,
                        )
                    )
                active_target_states["pi"] = (
                    "provider",
                    str(p_name),
                    str(p_model) if p_model else None,
                )
        except Exception:
            pass

    return items, active_target_states


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
                    else acc_store.exists(it.payload.target, it.name)
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
                already_set = cur_ts and cur_ts.active_type not in (None, "none")
                status = ""
                if already_set and cur_ts.active_name != a_name:
                    status = (
                        f" [will overwrite active '{cur_ts.active_name}']"
                        if force
                        else f" [kept active '{cur_ts.active_name}']"
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
        already_set = cur_ts and cur_ts.active_type not in (None, "none")
        if already_set and not force and cur_ts.active_name != a_name:
            if not quiet:
                print(
                    f"  • Kept active state for {target} "
                    f"('{cur_ts.active_name}', use --force to overwrite)"
                )
            continue
        state_store.set_target_state(target, a_type, a_name, a_model)
        if not quiet:
            m_str = f"/{a_model}" if a_model else ""
            tag = (
                " (--force)"
                if (already_set and force and cur_ts.active_name != a_name)
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
