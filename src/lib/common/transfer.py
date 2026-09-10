from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from lib.common.common_store import SECRET_FILE_MODE, atomic_write_bytes
from lib.common.errors import SwitchError

INTEROPERABLE_TOOLS = ("cpx", "opx", "clpx", "cupx")


def build_interoperable_export(
    target_tool: str,
    active_provider: str,
    providers: dict[str, dict[str, Any]],
    *,
    active_model: str | None = None,
) -> dict[str, Any]:
    """Render normalized OpenAI-compatible provider data for a target CLI."""
    if target_tool not in INTEROPERABLE_TOOLS:
        raise SwitchError(f"unsupported export target: {target_tool}")

    converted: dict[str, dict[str, Any]] = {}
    for provider, info in providers.items():
        if not isinstance(provider, str) or not isinstance(info, dict):
            continue
        base_url = info.get("base_url")
        if not isinstance(base_url, str) or not base_url:
            continue
        name = info.get("name")
        api_key = info.get("api_key")
        models = info.get("models")
        model = info.get("model")
        converted[provider] = {
            "base_url": base_url,
            "name": name if isinstance(name, str) and name else provider,
            "api_key": api_key if isinstance(api_key, str) else "",
            "models": models,
            "model": model if isinstance(model, str) else None,
        }

    active = active_provider if active_provider in converted else ""
    if target_tool == "cpx":
        return {
            "type": "codex-provider",
            "version": 1,
            "active_provider": active,
            "providers": {
                provider: {
                    "config": {
                        "base_url": info["base_url"],
                        "name": info["name"],
                        "requires_openai_auth": True,
                        "wire_api": "responses",
                    },
                    "auth": {"OPENAI_API_KEY": info["api_key"]},
                }
                for provider, info in converted.items()
            },
        }

    if target_tool == "opx":

        def opencode_models(value: Any) -> dict[str, Any]:
            if isinstance(value, dict):
                return value
            if isinstance(value, list):
                return {
                    model_id: {"name": model_id}
                    for model_id in value
                    if isinstance(model_id, str) and model_id
                }
            return {}

        return {
            "type": "opencode-provider",
            "version": 1,
            "current_provider": active,
            "current_model": active_model if isinstance(active_model, str) else None,
            "providers": {
                provider: {
                    "config": {
                        "name": info["name"],
                        "npm": "@ai-sdk/openai",
                        "options": {"baseURL": info["base_url"]},
                        "models": opencode_models(info["models"]),
                    },
                    "auth": {"type": "api", "key": info["api_key"]},
                }
                for provider, info in converted.items()
            },
        }

    if target_tool == "clpx":
        return {
            "type": "claude-provider",
            "version": 1,
            "active_provider": active,
            "providers": {
                provider: {
                    "config": {
                        **{
                            "base_url": info["base_url"],
                            "name": info["name"],
                        },
                        **(
                            {"model": info["model"]}
                            if isinstance(info["model"], str) and info["model"]
                            else {}
                        ),
                    },
                    "auth": {"ANTHROPIC_AUTH_TOKEN": info["api_key"]},
                }
                for provider, info in converted.items()
            },
        }

    def cursor_models(value: Any) -> list[str]:
        if isinstance(value, list):
            return [model_id for model_id in value if isinstance(model_id, str)]
        if isinstance(value, dict):
            return [model_id for model_id in value if isinstance(model_id, str)]
        return []

    return {
        "type": "cursor-provider",
        "version": 1,
        "current_provider": active,
        "providers": {
            provider: {
                "base_url": info["base_url"],
                "api_key": info["api_key"],
                "api_key_cipher": "",
                "models": cursor_models(info["models"]),
            }
            for provider, info in converted.items()
        },
    }


def read_import_data(file_path: str | None) -> dict[str, Any]:
    if not file_path or file_path == "-":
        raw_data = sys.stdin.read()
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
    return data


def validate_export(data: dict[str, Any], expected_type: str) -> None:
    if data.get("type") != expected_type:
        found = data.get("type")
        raise SwitchError(
            f"invalid export file type: expected {expected_type}, found {found}"
        )
    version = data.get("version")
    if version != 1:
        raise SwitchError(f"unsupported version: {version}")


def write_export(payload: str, file_path: str | None, label: str) -> None:
    if not file_path or file_path == "-":
        sys.stdout.write(payload)
        return
    path = Path(file_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(
        path,
        payload.encode("utf-8"),
        secret=True,
        mode=SECRET_FILE_MODE,
    )
    print(f"exported {label} configuration and auth to {path}")
