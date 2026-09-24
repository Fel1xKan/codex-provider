from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from lib.common.common_store import atomic_write_bytes, ensure_private_dir
from lib.xpx.adapters.base import MergedProviderSpec, TargetAdapter, TargetStatus
from lib.xpx.store.catalog_store import ModelMetadata


def get_pi_config_file() -> Path:
    override = os.environ.get("PI_CONFIG_PATH")
    if override:
        return Path(override)
    override_home = os.environ.get("PI_HOME")
    if override_home:
        return Path(override_home) / ".pi" / "config.yaml"
    return Path.home() / ".pi" / "config.yaml"


def _build_pi_model_entry(meta: ModelMetadata) -> dict[str, Any]:
    has_reasoning = bool(
        meta.supported_reasoning_levels
        and not (
            len(meta.supported_reasoning_levels) == 1
            and str(meta.supported_reasoning_levels[0]).lower() == "none"
        )
    )
    entry: dict[str, Any] = {
        "id": meta.id,
        "reasoning": has_reasoning,
        "contextWindow": meta.context_window or 128000,
    }
    if has_reasoning:
        levels = (
            [
                lvl
                for lvl in meta.supported_reasoning_levels
                if lvl and str(lvl).lower() != "none"
            ]
            if meta.supported_reasoning_levels
            else []
        ) or ["low", "medium", "high", "xhigh", "max"]
        entry["thinkingLevelMap"] = {lvl: lvl for lvl in levels}
    return entry


class PiAdapter(TargetAdapter):
    name = "pi"
    display_name = "Pi Coding Agent"
    supported_protocols = ["openai"]
    binary_name = "pi"
    package_name = "@earendil-works/pi-coding-agent"

    def __init__(
        self,
        config_path: Path | None = None,
        models_path: Path | None = None,
    ) -> None:
        self._config_path = config_path
        self._models_path = models_path

    @property
    def config_file(self) -> Path:
        return self._config_path or get_pi_config_file()

    @property
    def agent_dir(self) -> Path:
        return self.config_file.parent / "agent"

    @property
    def models_path(self) -> Path:
        return self._models_path or (self.agent_dir / "models.json")

    def detect(self) -> bool:
        return self.config_file.parent.exists() or shutil.which("pi") is not None

    def get_status(self) -> TargetStatus:
        ver = self.get_cli_version()
        bin_p = self.get_binary_path()
        if not self.config_file.exists():
            return TargetStatus(
                installed=self.detect(),
                active_type="none",
                active_name="-",
                config_path=str(self.config_file),
                cli_version=ver,
                binary_path=bin_p,
            )
        try:
            data = yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
            pv = data.get("model_provider", {})
            return TargetStatus(
                installed=True,
                active_type="provider" if pv.get("name") else "none",
                active_name=pv.get("name", "unknown"),
                active_model=pv.get("model"),
                config_path=str(self.config_file),
                cli_version=ver,
                binary_path=bin_p,
            )
        except Exception:
            return TargetStatus(
                installed=True,
                active_type="none",
                active_name="error",
                config_path=str(self.config_file),
                cli_version=ver,
                binary_path=bin_p,
            )

    def _generate_pi_models(
        self,
        provider_name: str,
        applied_model: str | None = None,
        previous_model: str | None = None,
    ) -> list[dict[str, Any]]:
        from lib.xpx.models.catalog import (
            enrich_model_metadata,
            load_shared_catalog_data,
        )
        from lib.xpx.store.catalog_store import CatalogStore
        from lib.xpx.store.provider_store import ProviderStore

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

        pi_models = [_build_pi_model_entry(meta) for meta in models_map.values()]
        pi_models.sort(key=lambda x: str(x.get("id", "")).lower())
        return pi_models

    def refresh_catalog(self, provider_name: str | None = None) -> bool:
        if not self.config_file.is_file():
            return False
        try:
            data = yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
            pv = data.get("model_provider", {})
            active_pv = str(pv.get("name") or "")
            if not active_pv:
                return False
            if provider_name and provider_name != active_pv:
                return False

            current_model = pv.get("model")

            ensure_private_dir(self.agent_dir)
            models_data: dict[str, Any] = {}
            if self.models_path.is_file():
                try:
                    models_data = json.loads(
                        self.models_path.read_text(encoding="utf-8")
                    )
                    if not isinstance(models_data, dict):
                        models_data = {}
                except Exception:
                    models_data = {}

            providers = models_data.setdefault("providers", {})
            if not isinstance(providers, dict):
                providers = {}
                models_data["providers"] = providers

            prov = providers.setdefault(active_pv, {})
            if not isinstance(prov, dict):
                prov = {}
                providers[active_pv] = prov

            prov["baseUrl"] = pv.get("api_base", "")
            prov["api"] = "openai-completions"
            prov["apiKey"] = pv.get("api_key", "")
            prov["models"] = self._generate_pi_models(
                provider_name=active_pv,
                applied_model=current_model,
                previous_model=None,
            )

            payload_models = (
                json.dumps(models_data, indent=2, ensure_ascii=False) + "\n"
            ).encode("utf-8")
            atomic_write_bytes(self.models_path, payload_models)
            return True
        except Exception:
            return False

    def apply(self, spec: MergedProviderSpec) -> None:
        previous_model: str | None = None
        ensure_private_dir(self.config_file.parent)
        data = {}
        if self.config_file.exists():
            try:
                data = (
                    yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
                )
                if isinstance(data, dict):
                    pv_info = data.get("model_provider", {})
                    if isinstance(pv_info, dict):
                        raw_model = pv_info.get("model")
                        if isinstance(raw_model, str):
                            previous_model = raw_model
            except Exception:
                data = {}
        data["model_provider"] = {
            "name": spec.name,
            "api_base": spec.base_url,
            "api_key": spec.api_key,
            "model": spec.model or "default",
        }
        if spec.options:
            data["model_provider"]["options"] = spec.options
        payload = yaml.dump(data, allow_unicode=True).encode("utf-8")
        atomic_write_bytes(self.config_file, payload)

        # Write models.json in agent_dir
        ensure_private_dir(self.agent_dir)
        models_data: dict[str, Any] = {}
        if self.models_path.is_file():
            try:
                models_data = json.loads(self.models_path.read_text(encoding="utf-8"))
                if not isinstance(models_data, dict):
                    models_data = {}
            except Exception:
                models_data = {}

        providers = models_data.setdefault("providers", {})
        if not isinstance(providers, dict):
            providers = {}
            models_data["providers"] = providers

        prov = providers.setdefault(spec.name, {})
        if not isinstance(prov, dict):
            prov = {}
            providers[spec.name] = prov

        prov["baseUrl"] = spec.base_url
        prov["api"] = "openai-completions"
        prov["apiKey"] = spec.api_key
        prov["models"] = self._generate_pi_models(
            provider_name=spec.name,
            applied_model=spec.model,
            previous_model=previous_model,
        )

        payload_models = (
            json.dumps(models_data, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        atomic_write_bytes(self.models_path, payload_models)

    def clear(self) -> None:
        if self.config_file.exists():
            try:
                data = (
                    yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
                )
                prev_name = ""
                if isinstance(data, dict):
                    pv_info = data.get("model_provider", {})
                    if isinstance(pv_info, dict):
                        prev_name = str(pv_info.get("name") or "")
                    data.pop("model_provider", None)
                    atomic_write_bytes(
                        self.config_file, yaml.dump(data).encode("utf-8")
                    )

                if prev_name and self.models_path.is_file():
                    try:
                        m_data = json.loads(
                            self.models_path.read_text(encoding="utf-8")
                        )
                        if isinstance(m_data, dict) and "providers" in m_data:
                            providers = m_data.get("providers", {})
                            if isinstance(providers, dict) and prev_name in providers:
                                del providers[prev_name]
                                if not providers:
                                    self.models_path.unlink(missing_ok=True)
                                else:
                                    atomic_write_bytes(
                                        self.models_path,
                                        (
                                            json.dumps(
                                                m_data, indent=2, ensure_ascii=False
                                            )
                                            + "\n"
                                        ).encode("utf-8"),
                                    )
                    except Exception:
                        pass
            except Exception:
                pass

    def ping(
        self, prompt: str, timeout: int, spec: MergedProviderSpec | None = None
    ) -> tuple[bool, str]:
        cmd = ["pi", "--prompt", prompt]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            out = proc.stdout.strip() or proc.stderr.strip()
            return proc.returncode == 0, out
        except Exception as exc:
            return False, str(exc)
