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


def _normalize_pi_thinking_level(effort: str | None) -> str | None:
    if not effort:
        return None
    eff = str(effort).strip().lower()
    if eff in ("none", "off", "false", "0"):
        return "off"
    if eff == "ultra":
        return "max"
    valid = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
    if eff in valid:
        return eff
    return None


def _resolve_model_effort(
    provider_name: str,
    model_id: str | None,
    explicit_effort: str | None = None,
) -> str | None:
    if explicit_effort:
        return explicit_effort
    if not model_id:
        return None
    clean_id = model_id.split("/", 1)[-1].strip()
    try:
        from lib.xpx.store.catalog_store import CatalogStore

        cat = CatalogStore().get(provider_name)
        if cat and clean_id in cat.models:
            meta = cat.models[clean_id]
            if meta.default_reasoning_level:
                return meta.default_reasoning_level
    except Exception:
        pass
    try:
        from lib.xpx.models.catalog import enrich_model_metadata

        meta = enrich_model_metadata(clean_id)
        if meta.default_reasoning_level:
            return meta.default_reasoning_level
    except Exception:
        pass
    return None


def _build_pi_model_entry(meta: ModelMetadata) -> dict[str, Any]:
    has_reasoning = bool(
        meta.supported_reasoning_levels
        and not (
            len(meta.supported_reasoning_levels) == 1
            and str(meta.supported_reasoning_levels[0]).lower() in ("none", "off")
        )
    )
    entry: dict[str, Any] = {
        "id": meta.id,
        "reasoning": has_reasoning,
        "contextWindow": meta.context_window or 128000,
    }
    if meta.max_output_tokens:
        entry["maxTokens"] = meta.max_output_tokens

    if has_reasoning:
        levels = (
            [
                lvl
                for lvl in meta.supported_reasoning_levels
                if lvl and str(lvl).lower() not in ("none", "off")
            ]
            if meta.supported_reasoning_levels
            else []
        ) or ["low", "medium", "high", "xhigh", "max"]
        t_map: dict[str, Any] = {lvl: lvl for lvl in levels}
        t_map["off"] = None
        if "medium" in levels and "minimal" not in t_map:
            t_map["minimal"] = "low" if "low" in levels else levels[0]
        entry["thinkingLevelMap"] = t_map
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
        settings_path: Path | None = None,
        auth_path: Path | None = None,
        agent_dir: Path | None = None,
    ) -> None:
        self._config_path = config_path
        self._models_path = models_path
        self._settings_path = settings_path
        self._auth_path = auth_path
        self._agent_dir = agent_dir

    @property
    def config_file(self) -> Path:
        return self._config_path or get_pi_config_file()

    @property
    def agent_dir(self) -> Path:
        if self._agent_dir:
            return self._agent_dir
        if self._config_path:
            return self._config_path.parent / "agent"
        override = os.environ.get("PI_CODING_AGENT_DIR")
        if override:
            return Path(override)
        override_home = os.environ.get("PI_HOME")
        if override_home:
            return Path(override_home) / ".pi" / "agent"
        return Path.home() / ".pi" / "agent"

    @property
    def models_path(self) -> Path:
        return self._models_path or (self.agent_dir / "models.json")

    @property
    def settings_path(self) -> Path:
        return self._settings_path or (self.agent_dir / "settings.json")

    @property
    def auth_path(self) -> Path:
        return self._auth_path or (self.agent_dir / "auth.json")

    def detect(self) -> bool:
        return (
            self.config_file.parent.exists()
            or self.agent_dir.exists()
            or shutil.which("pi") is not None
        )

    def get_status(self) -> TargetStatus:
        ver = self.get_cli_version()
        bin_p = self.get_binary_path()
        installed = self.detect()

        # Check settings.json first as it governs Pi's runtime provider/model/thinking
        if self.settings_path.is_file():
            try:
                st_data = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if isinstance(st_data, dict):
                    pv_name = st_data.get("defaultProvider")
                    model = st_data.get("defaultModel")
                    thinking = st_data.get("defaultThinkingLevel")
                    if pv_name:
                        extra = f"Thinking: {thinking}" if thinking else ""
                        return TargetStatus(
                            installed=True,
                            active_type="provider",
                            active_name=pv_name,
                            active_model=model,
                            config_path=str(self.settings_path),
                            extra_summary=extra,
                            cli_version=ver,
                            binary_path=bin_p,
                        )
            except Exception:
                pass

        if not self.config_file.exists():
            return TargetStatus(
                installed=installed,
                active_type="none",
                active_name="-",
                config_path=str(
                    self.settings_path
                    if self.settings_path.exists()
                    else self.config_file
                ),
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
        active_pv = ""
        current_model = None
        if self.settings_path.is_file():
            try:
                st_data = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if isinstance(st_data, dict):
                    active_pv = str(st_data.get("defaultProvider") or "")
                    current_model = st_data.get("defaultModel")
            except Exception:
                pass

        if not active_pv and self.config_file.is_file():
            try:
                data = (
                    yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
                )
                pv = data.get("model_provider", {})
                active_pv = str(pv.get("name") or "")
                if not current_model:
                    current_model = pv.get("model")
            except Exception:
                pass

        if not active_pv:
            return False
        if provider_name and provider_name != active_pv:
            return False
        target_pv = active_pv

        try:
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

            prov = providers.setdefault(target_pv, {})
            if not isinstance(prov, dict):
                prov = {}
                providers[target_pv] = prov

            if not prov.get("baseUrl") and self.config_file.is_file():
                try:
                    cfg_data = (
                        yaml.safe_load(self.config_file.read_text(encoding="utf-8"))
                        or {}
                    )
                    cfg_pv = cfg_data.get("model_provider", {})
                    if cfg_pv.get("name") == target_pv:
                        prov["baseUrl"] = cfg_pv.get("api_base", "")
                        prov["apiKey"] = cfg_pv.get("api_key", "")
                except Exception:
                    pass

            prov["api"] = "openai-completions"
            prov["models"] = self._generate_pi_models(
                provider_name=target_pv,
                applied_model=current_model if target_pv == active_pv else None,
                previous_model=None,
            )

            payload_models = (
                json.dumps(models_data, indent=2, ensure_ascii=False) + "\n"
            ).encode("utf-8")
            atomic_write_bytes(self.models_path, payload_models)

            if target_pv == active_pv and self.settings_path.is_file():
                try:
                    st_data = json.loads(self.settings_path.read_text(encoding="utf-8"))
                    if isinstance(st_data, dict):
                        changed = False
                        if not st_data.get("defaultModel") and current_model:
                            st_data["defaultModel"] = current_model
                            changed = True
                        eff = _resolve_model_effort(target_pv, current_model)
                        pi_th = _normalize_pi_thinking_level(eff)
                        if pi_th and not st_data.get("defaultThinkingLevel"):
                            st_data["defaultThinkingLevel"] = pi_th
                            changed = True
                        if changed:
                            atomic_write_bytes(
                                self.settings_path,
                                (
                                    json.dumps(st_data, indent=2, ensure_ascii=False)
                                    + "\n"
                                ).encode("utf-8"),
                            )
                except Exception:
                    pass

            return True
        except Exception:
            return False

    def apply(self, spec: MergedProviderSpec) -> None:
        clean_model = (spec.model or "").strip()
        prefix = f"{spec.name}/"
        if clean_model.startswith(prefix):
            clean_model = clean_model[len(prefix) :].strip()

        if not clean_model:
            try:
                from lib.xpx.store.provider_store import ProviderStore

                pv = ProviderStore().get(spec.name)
                if pv and pv.default_model:
                    clean_model = pv.default_model.strip()
                    if clean_model.startswith(prefix):
                        clean_model = clean_model[len(prefix) :].strip()
            except Exception:
                pass

        effort = _resolve_model_effort(spec.name, clean_model, spec.effort)
        pi_thinking = _normalize_pi_thinking_level(effort)

        ensure_private_dir(self.agent_dir)

        # 1. Update ~/.pi/agent/settings.json
        settings_data: dict[str, Any] = {}
        if self.settings_path.is_file():
            try:
                settings_data = json.loads(
                    self.settings_path.read_text(encoding="utf-8")
                )
                if not isinstance(settings_data, dict):
                    settings_data = {}
            except Exception:
                settings_data = {}

        settings_data["defaultProvider"] = spec.name
        if clean_model:
            settings_data["defaultModel"] = clean_model

        if pi_thinking:
            settings_data["defaultThinkingLevel"] = pi_thinking
            mt_levels = settings_data.setdefault("modelThinkingLevels", {})
            if not isinstance(mt_levels, dict):
                mt_levels = {}
                settings_data["modelThinkingLevels"] = mt_levels
            if clean_model:
                mt_levels[f"{spec.name}/{clean_model}"] = pi_thinking
        elif "defaultThinkingLevel" in settings_data and not spec.effort:
            mt_levels = settings_data.setdefault("modelThinkingLevels", {})
            if isinstance(mt_levels, dict) and clean_model:
                mt_levels[f"{spec.name}/{clean_model}"] = "off"

        payload_settings = (
            json.dumps(settings_data, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        atomic_write_bytes(self.settings_path, payload_settings)

        # 2. Update ~/.pi/agent/auth.json
        if spec.api_key:
            auth_data: dict[str, Any] = {}
            if self.auth_path.is_file():
                try:
                    auth_data = json.loads(self.auth_path.read_text(encoding="utf-8"))
                    if not isinstance(auth_data, dict):
                        auth_data = {}
                except Exception:
                    auth_data = {}
            auth_data[spec.name] = {
                "type": "api_key",
                "key": spec.api_key,
            }
            payload_auth = (
                json.dumps(auth_data, indent=2, ensure_ascii=False) + "\n"
            ).encode("utf-8")
            atomic_write_bytes(self.auth_path, payload_auth)

        # 3. Update ~/.pi/agent/models.json
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
        if spec.api_key:
            prov["apiKey"] = spec.api_key
        prov["models"] = self._generate_pi_models(
            provider_name=spec.name,
            applied_model=clean_model or spec.model,
            previous_model=None,
        )

        payload_models = (
            json.dumps(models_data, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        atomic_write_bytes(self.models_path, payload_models)

        # 4. Update legacy ~/.pi/config.yaml
        ensure_private_dir(self.config_file.parent)
        data: dict[str, Any] = {}
        if self.config_file.exists():
            try:
                data = (
                    yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
                )
                if not isinstance(data, dict):
                    data = {}
            except Exception:
                data = {}
        data["model_provider"] = {
            "name": spec.name,
            "api_base": spec.base_url,
            "api_key": spec.api_key,
            "model": clean_model or spec.model or "default",
        }
        if spec.options:
            data["model_provider"]["options"] = spec.options
        payload = yaml.dump(data, allow_unicode=True).encode("utf-8")
        atomic_write_bytes(self.config_file, payload)

    def clear(self) -> None:
        prev_name = ""
        # 1. Clear settings.json
        if self.settings_path.is_file():
            try:
                st_data = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if isinstance(st_data, dict):
                    prev_name = str(st_data.get("defaultProvider") or "")
                    st_data.pop("defaultProvider", None)
                    st_data.pop("defaultModel", None)
                    st_data.pop("defaultThinkingLevel", None)
                    mt_levels = st_data.get("modelThinkingLevels")
                    if isinstance(mt_levels, dict) and prev_name:
                        st_data["modelThinkingLevels"] = {
                            k: v
                            for k, v in mt_levels.items()
                            if not k.startswith(f"{prev_name}/")
                        }
                    atomic_write_bytes(
                        self.settings_path,
                        (
                            json.dumps(st_data, indent=2, ensure_ascii=False) + "\n"
                        ).encode("utf-8"),
                    )
            except Exception:
                pass

        # 2. Clear config.yaml
        if self.config_file.exists():
            try:
                data = (
                    yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
                )
                if isinstance(data, dict):
                    pv_info = data.get("model_provider", {})
                    if isinstance(pv_info, dict) and not prev_name:
                        prev_name = str(pv_info.get("name") or "")
                    data.pop("model_provider", None)
                    atomic_write_bytes(
                        self.config_file, yaml.dump(data).encode("utf-8")
                    )
            except Exception:
                pass

        # 3. Clear auth.json
        if prev_name and self.auth_path.is_file():
            try:
                auth_data = json.loads(self.auth_path.read_text(encoding="utf-8"))
                if isinstance(auth_data, dict) and prev_name in auth_data:
                    del auth_data[prev_name]
                    if not auth_data:
                        self.auth_path.unlink(missing_ok=True)
                    else:
                        atomic_write_bytes(
                            self.auth_path,
                            (
                                json.dumps(auth_data, indent=2, ensure_ascii=False)
                                + "\n"
                            ).encode("utf-8"),
                        )
            except Exception:
                pass

        # 4. Clear models.json
        if prev_name and self.models_path.is_file():
            try:
                m_data = json.loads(self.models_path.read_text(encoding="utf-8"))
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
                                    json.dumps(m_data, indent=2, ensure_ascii=False)
                                    + "\n"
                                ).encode("utf-8"),
                            )
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
