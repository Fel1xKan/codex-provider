from __future__ import annotations

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

CONFIG_NAMES = (
    "opencode.json",
    "opencode.jsonc",
    "opencode.json5",
    "opencode.config.json",
    "opencode.config.jsonc",
    "opencode.config.json5",
)


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
    ) -> None:
        self._config_dir = config_dir
        self._data_dir = data_dir

    @property
    def config_dir_path(self) -> Path:
        return self._config_dir or get_opencode_config_dir()

    @property
    def data_dir_path(self) -> Path:
        return self._data_dir or get_opencode_data_dir()

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

    def apply(self, spec: MergedProviderSpec) -> None:
        cfg = self.find_config_file()
        ensure_private_dir(cfg.parent)
        data: dict[str, Any] = {}
        if cfg.is_file():
            try:
                data = json5.loads(cfg.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
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

        options = prov_dict.setdefault("options", {})
        if not isinstance(options, dict):
            options = {}
            prov_dict["options"] = options
        options["baseURL"] = spec.base_url
        options["apiKey"] = spec.api_key

        if spec.headers:
            options["headers"] = dict(spec.headers)

        # Set model
        if spec.model:
            model_val = spec.model
            if not model_val.startswith(f"{spec.name}/"):
                model_val = f"{spec.name}/{model_val}"
            data["model"] = model_val

        atomic_write_bytes(
            cfg, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        )

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
