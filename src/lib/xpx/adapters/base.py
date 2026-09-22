from __future__ import annotations

import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


def find_node_package_manager() -> str | None:
    """Detect available Node package manager (npm, pnpm, or bun)."""
    for pm in ("npm", "pnpm", "bun"):
        if shutil.which(pm):
            return pm
    return None


@dataclass
class TargetStatus:
    """Current status of a target client for reporting in xpx status."""

    installed: bool
    active_type: str  # "provider" | "account" | "official" | "none"
    active_name: str
    active_model: str | None = None
    config_path: str = ""
    extra_summary: str = ""
    cli_version: str | None = None
    binary_path: str | None = None


@dataclass
class MergedProviderSpec:
    """Merged configuration from universal base + target overrides + CLI ad-hoc."""

    name: str
    base_url: str
    api_key: str
    protocol: str = "openai"
    model: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    fast: bool | None = None
    wire_api: str | None = None
    web_search: bool | None = None
    options: dict[str, Any] = field(default_factory=dict)


class TargetAdapter(ABC):
    """Abstract base class for all target client adapters."""

    name: str
    display_name: str
    binary_name: str = ""
    package_name: str | None = None
    install_guide: str = ""
    supported_protocols: list[str] = ["openai"]
    supports_fast: bool = False
    supports_web_search: bool = False
    supports_wire_api: bool = False

    def get_binary_path(self) -> str | None:
        """Locate executable binary for this agent CLI."""
        if not self.binary_name:
            return None
        return shutil.which(self.binary_name)

    def get_cli_version(self) -> str | None:
        """Extract semantic version of the installed CLI binary."""
        if hasattr(self, "_cached_cli_version"):
            return self._cached_cli_version

        bin_path = self.get_binary_path()
        if not bin_path:
            self._cached_cli_version = None
            return None

        try:
            res = subprocess.run(
                [bin_path, "--version"],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            out = (res.stdout or res.stderr or "").strip()
            match = re.search(r"(\d+\.\d+\.\d+(?:-[\w\.]+)?|\d+\.\d+)", out)
            if match:
                self._cached_cli_version = f"v{match.group(1)}"
            else:
                self._cached_cli_version = out.splitlines()[0][:15] if out else None
        except Exception:
            self._cached_cli_version = None

        return self._cached_cli_version

    def install(self, dry_run: bool = False) -> tuple[bool, str]:
        """Install this agent CLI."""
        if self.package_name:
            pm = find_node_package_manager()
            if not pm:
                return (
                    False,
                    "Node.js package manager (npm / pnpm / bun) not found. "
                    "Please install Node.js first: https://nodejs.org",
                )
            cmd = [pm, "install", "-g", self.package_name]
            if dry_run:
                return True, f"would execute: {' '.join(cmd)}"
            try:
                res = subprocess.run(cmd, check=False)
                if res.returncode == 0:
                    if hasattr(self, "_cached_cli_version"):
                        delattr(self, "_cached_cli_version")
                    return (
                        True,
                        f"Successfully installed {self.display_name} via {pm}.",
                    )
                return False, f"{pm} install exited with code {res.returncode}"
            except Exception as exc:
                return False, str(exc)

        if self.install_guide:
            return True, self.install_guide

        return (
            False,
            f"Automated installation not configured for {self.display_name}.",
        )

    def update(self, dry_run: bool = False) -> tuple[bool, str]:
        """Update this agent CLI to the latest version."""
        bin_path = self.get_binary_path()
        native_cmds: dict[str, list[str]] = {
            "codex": [bin_path or "codex", "update"],
            "claude": [bin_path or "claude", "update"],
            "opencode": [bin_path or "opencode", "upgrade"],
            "agy": [bin_path or "agy", "update"],
        }
        if bin_path and self.binary_name in native_cmds:
            cmd = native_cmds[self.binary_name]
            if dry_run:
                return True, f"would execute: {' '.join(cmd)}"
            try:
                res = subprocess.run(cmd, check=False)
                if res.returncode == 0:
                    if hasattr(self, "_cached_cli_version"):
                        delattr(self, "_cached_cli_version")
                    return (
                        True,
                        f"Successfully updated {self.display_name} via native update.",
                    )
            except Exception:
                pass

        if self.package_name:
            pm = find_node_package_manager()
            if not pm:
                return (
                    False,
                    "Node.js package manager (npm / pnpm / bun) not found. "
                    "Please install Node.js first: https://nodejs.org",
                )
            cmd = [pm, "install", "-g", f"{self.package_name}@latest"]
            if dry_run:
                return True, f"would execute: {' '.join(cmd)}"
            try:
                res = subprocess.run(cmd, check=False)
                if res.returncode == 0:
                    if hasattr(self, "_cached_cli_version"):
                        delattr(self, "_cached_cli_version")
                    return (
                        True,
                        f"Successfully updated {self.display_name} via {pm}.",
                    )
                return False, f"{pm} update exited with code {res.returncode}"
            except Exception as exc:
                return False, str(exc)

        if self.install_guide:
            return True, self.install_guide

        return False, f"Automated update not configured for {self.display_name}."

    @abstractmethod
    def detect(self) -> bool:
        """Check whether the client is installed or configured on this machine."""
        pass

    @abstractmethod
    def get_status(self) -> TargetStatus:
        """Read native configuration to determine activation state."""
        pass

    @abstractmethod
    def apply(self, spec: MergedProviderSpec) -> None:
        """Render and atomically write configuration to native client files."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Reset the client to official/default state or clear credentials."""
        pass

    @abstractmethod
    def ping(
        self, prompt: str, timeout: int, spec: MergedProviderSpec | None = None
    ) -> tuple[bool, str]:
        """Invoke the client executable for an end-to-end question/answer probe.

        Returns (success, stdout/summary or error message).
        """
        pass
