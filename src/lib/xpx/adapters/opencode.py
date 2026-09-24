from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import json5

from lib.common.common_store import atomic_write_bytes, ensure_private_dir
from lib.common.constants import SECRET_FILE_MODE
from lib.common.errors import SwitchError
from lib.xpx.adapters.base import MergedProviderSpec, TargetAdapter, TargetStatus
from lib.xpx.models.catalog import enrich_model_metadata, load_shared_catalog_data
from lib.xpx.store.catalog_store import CatalogStore, ModelMetadata
from lib.xpx.store.provider_store import ProviderStore

CONFIG_NAMES = (
    "opencode.json",
    "opencode.jsonc",
    "opencode.json5",
    "opencode.config.json",
    "opencode.config.jsonc",
    "opencode.config.json5",
)

DEFAULT_OPENCODE_VARIANT_NAMES = ("low", "medium", "high", "xhigh", "max")


def _build_opencode_model_entry(
    meta: ModelMetadata,
    existing_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = (
        dict(existing_entry) if isinstance(existing_entry, dict) else {}
    )

    display_name = meta.display_name or meta.id
    if display_name:
        entry["name"] = display_name

    raw_limit = entry.get("limit")
    limit = dict(raw_limit) if isinstance(raw_limit, dict) else {}
    if meta.context_window and meta.context_window > 0:
        limit["context"] = meta.context_window
    if meta.max_output_tokens and meta.max_output_tokens > 0:
        limit["output"] = meta.max_output_tokens
    if limit:
        entry["limit"] = limit

    raw_variants = entry.get("variants")
    if not isinstance(raw_variants, dict) or not raw_variants:
        levels = meta.supported_reasoning_levels
        active_levels = (
            [lvl for lvl in levels if lvl and str(lvl).lower() != "none"]
            if levels
            else []
        )
        if active_levels:
            entry["variants"] = {
                name: {"reasoningEffort": name} for name in active_levels
            }
        elif levels and len(levels) == 1 and str(levels[0]).lower() == "none":
            entry.pop("variants", None)
        else:
            entry["variants"] = {
                name: {"reasoningEffort": name}
                for name in DEFAULT_OPENCODE_VARIANT_NAMES
            }

    return entry


def get_opencode_config_dir() -> Path:
    override = os.environ.get("OPENCODE_CONFIG_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        cand = Path(xdg) / "opencode"
        default_dir = Path.home() / ".config" / "opencode"
        if cand.is_dir() or not default_dir.is_dir():
            return cand
    return Path.home() / ".config" / "opencode"


def get_opencode_data_dir() -> Path:
    override = os.environ.get("OPENCODE_DATA_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        cand = Path(xdg) / "opencode"
        default_dir = Path.home() / ".local" / "share" / "opencode"
        if cand.is_dir() or not default_dir.is_dir():
            return cand
    return Path.home() / ".local" / "share" / "opencode"


class OpenCodeAdapter(TargetAdapter):
    name = "opencode"
    display_name = "OpenCode CLI"
    supported_protocols = ["openai"]
    binary_name = "opencode"
    package_name = "opencode-ai"

    def __init__(
        self,
        config_dir: Path | None = None,
        data_dir: Path | None = None,
        models_path: Path | None = None,
    ) -> None:
        self._config_dir = config_dir
        self._data_dir = data_dir
        self._models_path = models_path

    @property
    def config_dir_path(self) -> Path:
        return self._config_dir or get_opencode_config_dir()

    @property
    def data_dir_path(self) -> Path:
        return self._data_dir or get_opencode_data_dir()

    @property
    def models_path(self) -> Path:
        return self._models_path or (self.config_dir_path / "models.json")

    def find_config_file(self) -> Path:
        cdir = self.config_dir_path
        for name in CONFIG_NAMES:
            cand = cdir / name
            if cand.is_file():
                return cand
        return cdir / "opencode.json"

    @property
    def auth_path(self) -> Path:
        return self.data_dir_path / "auth.json"

    def detect(self) -> bool:
        return self.config_dir_path.is_dir() or shutil.which("opencode") is not None

    def get_status(self) -> TargetStatus:
        ver = self.get_cli_version()
        bin_p = self.get_binary_path()
        cfg = self.find_config_file()
        if not cfg.is_file():
            return TargetStatus(
                installed=self.detect(),
                active_type="none",
                active_name="-",
                config_path=str(cfg),
                cli_version=ver,
                binary_path=bin_p,
            )
        try:
            raw = cfg.read_text(encoding="utf-8")
            data = json5.loads(raw)
            if not isinstance(data, dict):
                return TargetStatus(
                    installed=True,
                    active_type="none",
                    active_name="-",
                    config_path=str(cfg),
                    cli_version=ver,
                    binary_path=bin_p,
                )
            model_str = data.get("model", "")
            active_provider = ""
            active_model = None
            if isinstance(model_str, str) and model_str:
                if "/" in model_str:
                    active_provider, active_model = model_str.split("/", 1)
                else:
                    active_provider = model_str
                    active_model = model_str
            if not active_provider:
                # check provider section
                providers = data.get("provider", {})
                if isinstance(providers, dict) and providers:
                    active_provider = next(iter(providers.keys()))
            return TargetStatus(
                installed=True,
                active_type="provider" if active_provider else "none",
                active_name=active_provider or "-",
                active_model=active_model,
                config_path=str(cfg),
                cli_version=ver,
                binary_path=bin_p,
            )
        except Exception as exc:
            return TargetStatus(
                installed=True,
                active_type="error",
                active_name=f"parse error: {exc}",
                config_path=str(cfg),
                cli_version=ver,
                binary_path=bin_p,
            )

    def _generate_opencode_models(
        self,
        provider_name: str,
        applied_model: str | None = None,
        previous_model: str | None = None,
        existing_models: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        cat_store = CatalogStore()
        catalog = cat_store.get(provider_name)
        models_map: dict[str, ModelMetadata] = {}
        if catalog and catalog.models:
            models_map.update(catalog.models)

        prefix = f"{provider_name}/"
        if applied_model and applied_model.strip():
            m_clean = applied_model.strip()
            if m_clean.startswith(prefix):
                m_clean = m_clean[len(prefix) :].strip()
            if m_clean not in models_map:
                models_map[m_clean] = enrich_model_metadata(m_clean)

        if previous_model and previous_model.strip():
            p_clean = previous_model.strip()
            if p_clean.startswith(prefix):
                p_clean = p_clean[len(prefix) :].strip()
            if p_clean not in models_map:
                models_map[p_clean] = enrich_model_metadata(p_clean)

        try:
            pv = ProviderStore().get(provider_name)
            if pv and pv.default_model and pv.default_model.strip():
                d_clean = pv.default_model.strip()
                if d_clean.startswith(prefix):
                    d_clean = d_clean[len(prefix) :].strip()
                if d_clean not in models_map:
                    models_map[d_clean] = enrich_model_metadata(d_clean)
        except Exception:
            pass

        if existing_models and isinstance(existing_models, dict):
            for k in existing_models:
                if k not in models_map:
                    models_map[k] = enrich_model_metadata(k)

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

        existing = existing_models if isinstance(existing_models, dict) else {}
        result: dict[str, dict[str, Any]] = {}
        for mid in sorted(models_map.keys(), key=lambda s: s.lower()):
            result[mid] = _build_opencode_model_entry(
                models_map[mid], existing.get(mid)
            )
        return result

    def refresh_catalog(self, provider_name: str | None = None) -> bool:
        cfg = self.find_config_file()
        if not cfg.is_file():
            return False
        try:
            data = json5.loads(cfg.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return False

            model_str = data.get("model", "")
            active_provider = ""
            current_model: str | None = None
            if isinstance(model_str, str) and model_str:
                if "/" in model_str:
                    active_provider, current_model = model_str.split("/", 1)
                else:
                    active_provider = model_str
                    current_model = model_str
            if not active_provider:
                providers = data.get("provider", {})
                if isinstance(providers, dict) and providers:
                    active_provider = next(iter(providers.keys()))

            if not active_provider:
                return False
            if provider_name and provider_name != active_provider:
                return False

            providers = data.setdefault("provider", {})
            if not isinstance(providers, dict):
                providers = {}
                data["provider"] = providers
            prov_dict = providers.setdefault(active_provider, {})
            if not isinstance(prov_dict, dict):
                prov_dict = {}
                providers[active_provider] = prov_dict

            if "npm" not in prov_dict:
                prov_dict["npm"] = "@ai-sdk/openai-compatible"
            if "name" not in prov_dict:
                prov_dict["name"] = active_provider

            opencode_models = self._generate_opencode_models(
                provider_name=active_provider,
                applied_model=current_model,
                previous_model=None,
                existing_models=prov_dict.get("models"),
            )
            prov_dict["models"] = opencode_models

            atomic_write_bytes(
                cfg,
                (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
            )

            models_catalog = [
                {
                    "id": mid,
                    "name": entry.get("name", mid),
                    **({"limit": entry["limit"]} if "limit" in entry else {}),
                    **({"variants": entry["variants"]} if "variants" in entry else {}),
                }
                for mid, entry in opencode_models.items()
            ]
            models_payload = (
                json.dumps(
                    {"provider": active_provider, "models": models_catalog},
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8")
            atomic_write_bytes(self.models_path, models_payload)
            return True
        except Exception:
            return False

    def apply(self, spec: MergedProviderSpec) -> None:
        cfg = self.find_config_file()
        ensure_private_dir(cfg.parent)
        data: dict[str, Any] = {}
        previous_model: str | None = None
        if cfg.is_file():
            try:
                data = json5.loads(cfg.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
                else:
                    raw_model = data.get("model")
                    if isinstance(raw_model, str):
                        previous_model = raw_model
            except Exception as exc:
                raise SwitchError(f"unable to parse {cfg}: {exc}") from exc

        providers = data.setdefault("provider", {})
        if not isinstance(providers, dict):
            providers = {}
            data["provider"] = providers

        prov_dict = providers.setdefault(spec.name, {})
        if not isinstance(prov_dict, dict):
            prov_dict = {}
            providers[spec.name] = prov_dict

        if "npm" not in prov_dict:
            prov_dict["npm"] = "@ai-sdk/openai-compatible"
        if "name" not in prov_dict:
            prov_dict["name"] = spec.name

        options = prov_dict.setdefault("options", {})
        if not isinstance(options, dict):
            options = {}
            prov_dict["options"] = options
        options["baseURL"] = spec.base_url
        options["apiKey"] = spec.api_key

        if spec.headers:
            options["headers"] = dict(spec.headers)

        # Generate and update models for OpenCode
        opencode_models = self._generate_opencode_models(
            provider_name=spec.name,
            applied_model=spec.model,
            previous_model=previous_model,
            existing_models=prov_dict.get("models"),
        )
        prov_dict["models"] = opencode_models

        # Set model
        if spec.model:
            model_val = spec.model
            if not model_val.startswith(f"{spec.name}/"):
                model_val = f"{spec.name}/{model_val}"
            data["model"] = model_val

        atomic_write_bytes(
            cfg, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        )

        # Emit models.json in OpenCode config dir as well
        models_catalog = [
            {
                "id": mid,
                "name": entry.get("name", mid),
                **({"limit": entry["limit"]} if "limit" in entry else {}),
                **({"variants": entry["variants"]} if "variants" in entry else {}),
            }
            for mid, entry in opencode_models.items()
        ]
        models_payload = (
            json.dumps(
                {"provider": spec.name, "models": models_catalog},
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
        atomic_write_bytes(self.models_path, models_payload)

        # Also write auth if data dir exists or needs auth.json
        if self.data_dir_path.is_dir() or spec.api_key:
            ensure_private_dir(self.data_dir_path)
            auth_data: dict[str, Any] = {}
            if self.auth_path.is_file():
                try:
                    auth_data = json.loads(self.auth_path.read_text(encoding="utf-8"))
                    if not isinstance(auth_data, dict):
                        auth_data = {}
                except Exception:
                    auth_data = {}
            auth_data[spec.name] = {"apiKey": spec.api_key}
            atomic_write_bytes(
                self.auth_path,
                (json.dumps(auth_data, indent=2) + "\n").encode("utf-8"),
                secret=True,
                mode=SECRET_FILE_MODE,
            )

    def clear(self) -> None:
        cfg = self.find_config_file()
        if cfg.is_file():
            try:
                data = json5.loads(cfg.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.pop("model", None)
                    atomic_write_bytes(
                        cfg,
                        (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode(
                            "utf-8"
                        ),
                    )
            except Exception as exc:
                raise SwitchError(f"unable to reset {cfg}: {exc}") from exc
        if self.models_path.is_file():
            with contextlib.suppress(OSError):
                self.models_path.unlink()

    def ping(
        self, prompt: str, timeout: int, spec: MergedProviderSpec | None = None
    ) -> tuple[bool, str]:
        cmd = ["opencode", "run", prompt]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            out = proc.stdout.strip() or proc.stderr.strip()
            return proc.returncode == 0, out
        except Exception as exc:
            return False, str(exc)
