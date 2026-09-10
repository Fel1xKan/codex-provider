from __future__ import annotations

import json
import os
import urllib.error
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib.common.common_store import atomic_write_bytes
from lib.common.constants import MODEL_CATALOG_MAX_BYTES, MODEL_CATALOG_URL
from lib.common.errors import SwitchError
from lib.common.network import get_request_module

CATALOG_SCHEMA_VERSION = 1
_MODEL_FIELDS = (
    "display_name",
    "context_window",
    "max_output_tokens",
    "input_modalities",
)


@dataclass(frozen=True)
class CatalogResult:
    entries: dict[str, dict[str, Any]]
    aliases: dict[str, str]
    version: str
    source: str
    warning: str | None = None

    def metadata_for(self, model_id: str) -> dict[str, Any]:
        entry = self.entries.get(model_id)
        if entry is None:
            canonical = self.aliases.get(model_id)
            entry = self.entries.get(canonical) if canonical else None
        return dict(entry) if entry else {}


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    values = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return values or None


def _normalize_entry(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    entry: dict[str, Any] = {}
    display_name = raw.get("display_name")
    if isinstance(display_name, str) and display_name.strip():
        entry["display_name"] = display_name.strip()
    context_window = _positive_int(raw.get("context_window"))
    if context_window is not None:
        entry["context_window"] = context_window
    max_output_tokens = _positive_int(raw.get("max_output_tokens"))
    if max_output_tokens is not None:
        entry["max_output_tokens"] = max_output_tokens
    input_modalities = _string_list(raw.get("input_modalities"))
    if input_modalities:
        entry["input_modalities"] = input_modalities
    return entry


def _parse_catalog(payload: Any, source: str) -> CatalogResult:
    if not isinstance(payload, dict):
        raise SwitchError("model metadata catalog must be a JSON object")
    schema_version = payload.get("schema_version")
    if schema_version != CATALOG_SCHEMA_VERSION:
        raise SwitchError(
            f"unsupported model metadata catalog schema: {schema_version!r}"
        )
    raw_models = payload.get("models")
    if not isinstance(raw_models, dict):
        raise SwitchError("model metadata catalog must contain a models object")

    entries = {
        model_id: metadata
        for model_id, raw_entry in raw_models.items()
        if isinstance(model_id, str)
        and model_id.strip()
        and (metadata := _normalize_entry(raw_entry))
    }

    aliases: dict[str, str] = {}
    raw_aliases = payload.get("aliases", {})
    if isinstance(raw_aliases, dict):
        for alias, canonical in raw_aliases.items():
            if (
                isinstance(alias, str)
                and alias.strip()
                and isinstance(canonical, str)
                and canonical in entries
            ):
                aliases[alias] = canonical

    version = payload.get("catalog_version", "")
    if not isinstance(version, str):
        version = str(version)
    return CatalogResult(entries, aliases, version, source)


def _catalog_url() -> str:
    return os.environ.get("CODEX_PROVIDER_MODEL_CATALOG_URL", MODEL_CATALOG_URL)


def _read_json_bytes(raw: bytes, source: str) -> CatalogResult:
    if len(raw) > MODEL_CATALOG_MAX_BYTES:
        raise SwitchError(
            f"model metadata catalog exceeds {MODEL_CATALOG_MAX_BYTES} bytes"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError(
            f"invalid model metadata catalog from {source}: {exc}"
        ) from exc
    return _parse_catalog(payload, source)


def _fetch_remote(url: str) -> CatalogResult:
    request_module = get_request_module()
    request = request_module.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "codex-provider",
        },
    )
    try:
        with request_module.urlopen(request, timeout=10) as response:
            raw = response.read(MODEL_CATALOG_MAX_BYTES + 1)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        raise SwitchError(f"failed to fetch model metadata catalog: {exc}") from exc
    return _read_json_bytes(raw, "GitHub")


def _read_cache(cache_path: Path) -> CatalogResult | None:
    try:
        return _read_json_bytes(cache_path.read_bytes(), str(cache_path))
    except (OSError, SwitchError):
        return None


_MEMORY_CACHE: dict[tuple[str, str], CatalogResult] = {}
_REMOTE_CACHE: dict[str, CatalogResult] = {}


def load_model_catalog(cache_path: Path) -> CatalogResult:
    """Load the GitHub catalog, falling back to a previously valid cache.

    The catalog is supplemental metadata. Network or cache errors return an
    empty result so provider `/models` synchronization can still proceed.
    """

    url = _catalog_url()
    cache_key = (url, str(cache_path))
    cached_result = _MEMORY_CACHE.get(cache_key)
    if cached_result is not None:
        return cached_result

    remote = _REMOTE_CACHE.get(url)
    if remote is None:
        try:
            remote = _fetch_remote(url)
        except SwitchError as exc:
            remote = CatalogResult({}, {}, "", "none", str(exc))
        _REMOTE_CACHE[url] = remote

    if not remote.entries:
        cached = _read_cache(cache_path)
        warning = remote.warning
        if cached is not None:
            result = CatalogResult(
                cached.entries,
                cached.aliases,
                cached.version,
                "cache",
                f"{warning}; using cached model metadata" if warning else None,
            )
        else:
            result = remote
    else:
        with suppress(SwitchError):
            atomic_write_bytes(
                cache_path,
                json.dumps(
                    {
                        "schema_version": CATALOG_SCHEMA_VERSION,
                        "catalog_version": remote.version,
                        "models": remote.entries,
                        "aliases": remote.aliases,
                    },
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8")
                + b"\n",
            )
        result = CatalogResult(
            remote.entries,
            remote.aliases,
            remote.version,
            "remote",
        )

    _MEMORY_CACHE[cache_key] = result
    return result


def merge_metadata(
    fallback: dict[str, Any], explicit: dict[str, Any]
) -> dict[str, Any]:
    """Prefer metadata explicitly returned by the provider over the catalog."""

    merged = dict(fallback)
    merged.update(explicit)
    return merged


def catalog_fields() -> tuple[str, ...]:
    return _MODEL_FIELDS
