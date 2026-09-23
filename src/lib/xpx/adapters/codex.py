from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import tomlkit

from lib.common.common_store import atomic_write_bytes, ensure_private_dir
from lib.common.constants import SECRET_FILE_MODE
from lib.common.errors import SwitchError
from lib.xpx.adapters.base import MergedProviderSpec, TargetAdapter, TargetStatus
from lib.xpx.models.catalog import enrich_model_metadata, load_shared_catalog_data
from lib.xpx.store.catalog_store import CatalogStore, ModelMetadata
from lib.xpx.store.provider_store import ProviderStore

_FALLBACK_REASONING_LEVELS: tuple[str, ...] = (
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)

_LEVEL_DESCRIPTIONS = {
    "none": "Model does not reason",
    "minimal": "Fastest responses with minimal reasoning",
    "low": "Fast responses with lighter reasoning",
    "medium": "Balances speed and reasoning depth for everyday tasks",
    "high": "Greater reasoning depth for complex problems",
    "xhigh": "Extra high reasoning depth for complex problems",
    "max": "Maximum reasoning depth for the hardest problems",
    "ultra": "Maximum reasoning with automatic task delegation",
}

_PREFERRED_DEFAULT_LEVELS: tuple[str, ...] = (
    "medium",
    "high",
    "low",
    "minimal",
    "xhigh",
    "max",
    "ultra",
    "none",
)


def _pick_default_reasoning_level(
    levels: list[str], configured_default: str | None
) -> str:
    if configured_default and configured_default in levels:
        return configured_default
    for cand in _PREFERRED_DEFAULT_LEVELS:
        if cand in levels:
            return cand
    return levels[0] if levels else "medium"


def _build_codex_model_entry(meta: ModelMetadata) -> dict[str, Any]:
    levels = meta.supported_reasoning_levels or list(_FALLBACK_REASONING_LEVELS)
    def_level = _pick_default_reasoning_level(levels, meta.default_reasoning_level)
    supported_levels = [
        {"effort": eff, "description": _LEVEL_DESCRIPTIONS.get(eff, eff)}
        for eff in levels
    ]
    input_modalities = [
        m for m in meta.input_modalities if m in ("text", "image", "audio")
    ]
    if not input_modalities:
        input_modalities = ["text"]
    elif "text" not in input_modalities:
        input_modalities.insert(0, "text")

    ctx = meta.context_window or 1048576
    max_tokens = meta.max_output_tokens or 8192

    return {
        "slug": meta.id,
        "display_name": meta.display_name or meta.id,
        "description": f"Synced from provider /models: {meta.id}",
        "default_reasoning_level": def_level,
        "supported_reasoning_levels": supported_levels,
        "shell_type": "shell_command",
        "visibility": "list",
        "supported_in_api": True,
        "priority": 0,
        "base_instructions": "",
        "supports_reasoning_summaries": True,
        "default_reasoning_summary": "none",
        "support_verbosity": False,
        "apply_patch_tool_type": "freeform",
        "truncation_policy": {"mode": "bytes", "limit": 10000},
        "context_window": ctx,
        "max_context_window": ctx,
        "effective_context_window_percent": 95,
        "supports_parallel_tool_calls": True,
        "experimental_supported_tools": [],
        "input_modalities": input_modalities,
        "max_output_tokens": max_tokens,
    }


def get_codex_home() -> Path:
    override = os.environ.get("CODEX_HOME")
    if override:
        return Path(override)
    return Path.home() / ".codex"


class CodexAdapter(TargetAdapter):
    name = "codex"
    display_name = "Codex CLI"
    supported_protocols = ["openai"]
    binary_name = "codex"
    package_name = "@openai/codex"
    supports_fast = True
    supports_web_search = True
    supports_wire_api = True

    def __init__(self, home: Path | None = None) -> None:
        self._home = home

    @property
    def home_dir(self) -> Path:
        return self._home or get_codex_home()

    @property
    def config_path(self) -> Path:
        return self.home_dir / "config.toml"

    @property
    def auth_path(self) -> Path:
        return self.home_dir / "auth.json"

    @property
    def models_path(self) -> Path:
        return self.home_dir / "models.json"

    def detect(self) -> bool:
        return self.home_dir.is_dir() or shutil.which("codex") is not None

    def get_status(self) -> TargetStatus:
        ver = self.get_cli_version()
        bin_p = self.get_binary_path()
        if not self.config_path.is_file():
            return TargetStatus(
                installed=self.detect(),
                active_type="none",
                active_name="-",
                config_path=str(self.config_path),
                cli_version=ver,
                binary_path=bin_p,
            )
        try:
            doc = tomlkit.parse(self.config_path.read_text(encoding="utf-8"))
            active_provider = str(doc.get("model_provider", "") or "")
            active_model = doc.get("model")
            if active_model is not None:
                active_model = str(active_model)
            fast_mode = doc.get("service_tier") == "priority"
            extra = "fast" if fast_mode else ""
            if not active_provider or active_provider == "openai":
                return TargetStatus(
                    installed=True,
                    active_type="official" if active_provider == "openai" else "none",
                    active_name="openai" if active_provider == "openai" else "-",
                    active_model=active_model,
                    config_path=str(self.config_path),
                    extra_summary=extra,
                    cli_version=ver,
                    binary_path=bin_p,
                )
            return TargetStatus(
                installed=True,
                active_type="provider",
                active_name=active_provider,
                active_model=active_model,
                config_path=str(self.config_path),
                extra_summary=extra,
                cli_version=ver,
                binary_path=bin_p,
            )
        except Exception as exc:
            return TargetStatus(
                installed=True,
                active_type="error",
                active_name=f"parse error: {exc}",
                config_path=str(self.config_path),
                cli_version=ver,
                binary_path=bin_p,
            )

    def _generate_codex_models(
        self,
        provider_name: str,
        applied_model: str | None = None,
        previous_model: str | None = None,
    ) -> list[dict[str, Any]]:
        cat_store = CatalogStore()
        catalog = cat_store.get(provider_name)
        models_map: dict[str, ModelMetadata] = {}
        if catalog and catalog.models:
            models_map.update(catalog.models)

        if applied_model and applied_model.strip():
            m_clean = applied_model.strip()
            if m_clean not in models_map:
                models_map[m_clean] = enrich_model_metadata(m_clean)

        if previous_model and previous_model.strip():
            p_clean = previous_model.strip()
            if p_clean not in models_map:
                models_map[p_clean] = enrich_model_metadata(p_clean)

        try:
            pv = ProviderStore().get(provider_name)
            if pv and pv.default_model and pv.default_model.strip():
                d_clean = pv.default_model.strip()
                if d_clean not in models_map:
                    models_map[d_clean] = enrich_model_metadata(d_clean)
        except Exception:
            pass

        if not models_map:
            try:
                shared = load_shared_catalog_data()
                shared_models = shared.get("models") or {}
                if shared_models:
                    for mid in shared_models:
                        models_map[mid] = enrich_model_metadata(mid)
            except Exception:
                pass

        if not models_map:
            for mid in ("gpt-5.4", "gpt-5.5", "deepseek-v4-flash"):
                models_map[mid] = enrich_model_metadata(mid)

        codex_models = [_build_codex_model_entry(meta) for meta in models_map.values()]
        codex_models.sort(key=lambda x: str(x.get("slug", "")).lower())
        return codex_models

    def refresh_catalog(self, provider_name: str | None = None) -> bool:
        if not self.config_path.is_file():
            return False
        try:
            doc = tomlkit.parse(self.config_path.read_text(encoding="utf-8"))
            active_pv = str(doc.get("model_provider", "") or "")
            if not active_pv or active_pv == "openai":
                return False
            if provider_name and provider_name != active_pv:
                return False

            current_model = doc.get("model")
            if current_model is not None:
                current_model = str(current_model)

            codex_models = self._generate_codex_models(
                provider_name=active_pv,
                applied_model=current_model,
                previous_model=None,
            )

            payload = (
                json.dumps({"models": codex_models}, indent=2, ensure_ascii=False)
                + "\n"
            ).encode("utf-8")
            atomic_write_bytes(self.models_path, payload)

            models_path_str = str(self.models_path)
            if doc.get("model_catalog_json") != models_path_str:
                doc["model_catalog_json"] = models_path_str
                atomic_write_bytes(self.config_path, tomlkit.dumps(doc).encode("utf-8"))
            return True
        except Exception:
            return False

    def apply(self, spec: MergedProviderSpec) -> None:
        ensure_private_dir(self.home_dir)
        doc = tomlkit.document()
        previous_model: str | None = None
        if self.config_path.is_file():
            try:
                doc = tomlkit.parse(self.config_path.read_text(encoding="utf-8"))
                raw_prev = doc.get("model")
                if raw_prev is not None:
                    previous_model = str(raw_prev)
            except Exception as exc:
                raise SwitchError(f"unable to parse {self.config_path}: {exc}") from exc

        # Ensure model_providers table exists
        if "model_providers" not in doc or not isinstance(doc["model_providers"], dict):
            doc["model_providers"] = tomlkit.table()
        providers_table = doc["model_providers"]

        pv_table = tomlkit.table()
        pv_table["name"] = spec.name
        pv_table["base_url"] = spec.base_url
        pv_table["wire_api"] = spec.wire_api or "responses"
        pv_table["requires_openai_auth"] = True

        if spec.headers:
            headers_table = tomlkit.inline_table()
            for k, v in sorted(spec.headers.items()):
                headers_table.add(k, v)
            pv_table["http_headers"] = headers_table

        providers_table[spec.name] = pv_table

        # Top-level settings
        doc["model_provider"] = spec.name
        if spec.model:
            doc["model"] = spec.model

        if spec.fast is True:
            doc["service_tier"] = "priority"
        elif spec.fast is False and "service_tier" in doc:
            del doc["service_tier"]

        if spec.web_search is True:
            doc["web_search"] = "live"
        elif spec.web_search is False and "web_search" in doc:
            del doc["web_search"]

        # Generate models.json catalog for Codex
        codex_models = self._generate_codex_models(
            provider_name=spec.name,
            applied_model=spec.model,
            previous_model=previous_model,
        )
        catalog_payload = (
            json.dumps({"models": codex_models}, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        atomic_write_bytes(self.models_path, catalog_payload)

        doc["model_catalog_json"] = str(self.models_path)

        atomic_write_bytes(self.config_path, tomlkit.dumps(doc).encode("utf-8"))

        # Write auth
        auth_data = {}
        if self.auth_path.is_file():
            try:
                auth_data = json.loads(self.auth_path.read_text(encoding="utf-8"))
                if not isinstance(auth_data, dict):
                    auth_data = {}
            except Exception:
                auth_data = {}
        auth_data["OPENAI_API_KEY"] = spec.api_key
        atomic_write_bytes(
            self.auth_path,
            (json.dumps(auth_data, indent=2) + "\n").encode("utf-8"),
            secret=True,
            mode=SECRET_FILE_MODE,
        )

    def clear(self) -> None:
        if self.config_path.is_file():
            try:
                doc = tomlkit.parse(self.config_path.read_text(encoding="utf-8"))
                doc["model_provider"] = "openai"
                if "service_tier" in doc:
                    del doc["service_tier"]
                if "web_search" in doc:
                    del doc["web_search"]
                if "model_catalog_json" in doc:
                    del doc["model_catalog_json"]
                atomic_write_bytes(self.config_path, tomlkit.dumps(doc).encode("utf-8"))
            except Exception as exc:
                raise SwitchError(f"unable to reset {self.config_path}: {exc}") from exc
        if self.models_path.is_file():
            with contextlib.suppress(OSError):
                self.models_path.unlink()

    def ping(
        self, prompt: str, timeout: int, spec: MergedProviderSpec | None = None
    ) -> tuple[bool, str]:
        cmd = ["codex", "exec", prompt]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            out = proc.stdout.strip() or proc.stderr.strip()
            return proc.returncode == 0, out
        except Exception as exc:
            return False, str(exc)
