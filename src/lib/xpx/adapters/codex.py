from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import tomlkit

from lib.common.common_store import atomic_write_bytes, ensure_private_dir
from lib.common.constants import SECRET_FILE_MODE
from lib.common.errors import SwitchError
from lib.xpx.adapters.base import MergedProviderSpec, TargetAdapter, TargetStatus


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

    def apply(self, spec: MergedProviderSpec) -> None:
        ensure_private_dir(self.home_dir)
        doc = tomlkit.document()
        if self.config_path.is_file():
            try:
                doc = tomlkit.parse(self.config_path.read_text(encoding="utf-8"))
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
                atomic_write_bytes(self.config_path, tomlkit.dumps(doc).encode("utf-8"))
            except Exception as exc:
                raise SwitchError(f"unable to reset {self.config_path}: {exc}") from exc

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
