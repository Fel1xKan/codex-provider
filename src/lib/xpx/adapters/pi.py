from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import yaml

from lib.common.common_store import atomic_write_bytes, ensure_private_dir
from lib.xpx.adapters.base import MergedProviderSpec, TargetAdapter, TargetStatus


def get_pi_config_file() -> Path:
    override = os.environ.get("PI_CONFIG_PATH")
    if override:
        return Path(override)
    override_home = os.environ.get("PI_HOME")
    if override_home:
        return Path(override_home) / ".pi" / "config.yaml"
    return Path.home() / ".pi" / "config.yaml"


class PiAdapter(TargetAdapter):
    name = "pi"
    display_name = "Pi Coding Agent"
    supported_protocols = ["openai"]

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path

    @property
    def config_file(self) -> Path:
        return self._config_path or get_pi_config_file()

    def detect(self) -> bool:
        return self.config_file.parent.exists() or shutil.which("pi") is not None

    def get_status(self) -> TargetStatus:
        if not self.config_file.exists():
            return TargetStatus(
                installed=self.detect(),
                active_type="none",
                active_name="-",
                config_path=str(self.config_file),
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
            )
        except Exception:
            return TargetStatus(
                installed=True,
                active_type="none",
                active_name="error",
                config_path=str(self.config_file),
            )

    def apply(self, spec: MergedProviderSpec) -> None:
        ensure_private_dir(self.config_file.parent)
        data = {}
        if self.config_file.exists():
            try:
                data = (
                    yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
                )
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

    def clear(self) -> None:
        if self.config_file.exists():
            try:
                data = (
                    yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
                )
                data.pop("model_provider", None)
                atomic_write_bytes(self.config_file, yaml.dump(data).encode("utf-8"))
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
