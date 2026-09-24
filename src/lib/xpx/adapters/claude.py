from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from lib.common.common_store import atomic_write_bytes, ensure_private_dir
from lib.common.errors import SwitchError
from lib.xpx.adapters.base import MergedProviderSpec, TargetAdapter, TargetStatus


def get_claude_settings_path() -> Path:
    override = os.environ.get("CLAUDE_SETTINGS_PATH")
    if override:
        return Path(override)
    override_home = os.environ.get("CLAUDE_HOME")
    if override_home:
        return Path(override_home) / "settings.json"
    return Path.home() / ".claude" / "settings.json"


class ClaudeAdapter(TargetAdapter):
    name = "claude"
    display_name = "Claude Code"
    supported_protocols = ["anthropic", "openai"]

    binary_name = "claude"
    package_name = "@anthropic-ai/claude-code"

    def __init__(self, settings_path: Path | None = None) -> None:
        self._settings_path = settings_path

    @property
    def path(self) -> Path:
        return self._settings_path or get_claude_settings_path()

    def detect(self) -> bool:
        return self.path.parent.is_dir() or shutil.which("claude") is not None

    def get_status(self) -> TargetStatus:
        ver = self.get_cli_version()
        bin_p = self.get_binary_path()
        if not self.path.is_file():
            return TargetStatus(
                installed=self.detect(),
                active_type="none",
                active_name="-",
                config_path=str(self.path),
                cli_version=ver,
                binary_path=bin_p,
            )
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            env = data.get("env", {}) if isinstance(data, dict) else {}
            base_url = env.get("ANTHROPIC_BASE_URL")
            model = env.get("ANTHROPIC_MODEL")
            if base_url:
                active_name = str(env.get("XPX_PROVIDER_NAME") or base_url)
                return TargetStatus(
                    installed=True,
                    active_type="provider",
                    active_name=active_name,
                    active_model=model,
                    config_path=str(self.path),
                    cli_version=ver,
                    binary_path=bin_p,
                )
            return TargetStatus(
                installed=True,
                active_type="official",
                active_name="anthropic",
                active_model=model,
                config_path=str(self.path),
                cli_version=ver,
                binary_path=bin_p,
            )
        except Exception as exc:
            return TargetStatus(
                installed=True,
                active_type="error",
                active_name=f"read error: {exc}",
                config_path=str(self.path),
                cli_version=ver,
                binary_path=bin_p,
            )

    def apply(self, spec: MergedProviderSpec) -> None:
        ensure_private_dir(self.path.parent)
        data: dict[str, Any] = {}
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except Exception as exc:
                raise SwitchError(f"unable to parse {self.path}: {exc}") from exc

        env = data.setdefault("env", {})
        if not isinstance(env, dict):
            env = {}
            data["env"] = env

        # Anthropic SDK appends /v1/messages to baseURL.
        # Strip trailing /v1 to avoid /v1/v1/messages.
        base_url = spec.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]

        env["ANTHROPIC_BASE_URL"] = base_url
        env["ANTHROPIC_AUTH_TOKEN"] = spec.api_key
        env["ANTHROPIC_API_KEY"] = spec.api_key
        env["XPX_PROVIDER_NAME"] = spec.name
        if spec.model:
            env["ANTHROPIC_MODEL"] = spec.model
            env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = spec.model
            env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = spec.model
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = spec.model
            env["ANTHROPIC_SUBAGENT_MODEL"] = spec.model
            env["CLAUDE_CODE_SUBAGENT_MODEL"] = spec.model

        raw_json = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        atomic_write_bytes(self.path, raw_json.encode("utf-8"))

    def refresh_catalog(self, provider_name: str | None = None) -> bool:
        if not self.path.is_file():
            return False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            env = data.get("env")
            if not isinstance(env, dict):
                return False
            base_url = env.get("ANTHROPIC_BASE_URL")
            if not base_url:
                return False
            active_pv = env.get("XPX_PROVIDER_NAME")
            if provider_name and active_pv and provider_name != active_pv:
                return False

            pv_name = provider_name or active_pv
            if pv_name:
                from lib.xpx.store.provider_store import ProviderStore

                pv = ProviderStore().get(pv_name)
                if pv and pv.default_model:
                    default_model = pv.default_model
                    env["ANTHROPIC_MODEL"] = default_model
                    env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = default_model
                    env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = default_model
                    env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = default_model
                    env["ANTHROPIC_SUBAGENT_MODEL"] = default_model
                    env["CLAUDE_CODE_SUBAGENT_MODEL"] = default_model
                    raw_json = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
                    atomic_write_bytes(self.path, raw_json.encode("utf-8"))
                    return True
            return False
        except Exception:
            return False

    def clear(self) -> None:
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                env = data.get("env") if isinstance(data, dict) else None
                if isinstance(env, dict):
                    for key in [
                        "ANTHROPIC_BASE_URL",
                        "ANTHROPIC_AUTH_TOKEN",
                        "ANTHROPIC_API_KEY",
                        "XPX_PROVIDER_NAME",
                        "ANTHROPIC_MODEL",
                        "ANTHROPIC_DEFAULT_OPUS_MODEL",
                        "ANTHROPIC_DEFAULT_SONNET_MODEL",
                        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                        "ANTHROPIC_SUBAGENT_MODEL",
                        "CLAUDE_CODE_SUBAGENT_MODEL",
                    ]:
                        env.pop(key, None)
                    raw_json = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
                    atomic_write_bytes(self.path, raw_json.encode("utf-8"))
            except Exception as exc:
                raise SwitchError(f"unable to reset {self.path}: {exc}") from exc

    def ping(
        self, prompt: str, timeout: int, spec: MergedProviderSpec | None = None
    ) -> tuple[bool, str]:
        cmd = ["claude", "--version"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            out = proc.stdout.strip() or proc.stderr.strip()
            return proc.returncode == 0, out
        except Exception as exc:
            return False, str(exc)
