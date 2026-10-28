from __future__ import annotations

import os
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


# Lines that agent CLIs emit at startup and that never describe probe outcome.
_NOISE_PREFIXES = (
    "warning:",
    "warn:",
    "deprecationwarning:",
    "note:",
)


def _strip_noise(text: str) -> str:
    """Drop startup warnings so the real answer/error is what gets reported."""
    kept = [
        line
        for line in text.splitlines()
        if line.strip() and not line.strip().lower().startswith(_NOISE_PREFIXES)
    ]
    return "\n".join(kept).strip()


def run_probe_command(
    cmd: list[str],
    timeout: int,
    env: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Run an end-to-end agent probe and normalize the result.

    Shared by every adapter's `ping` so the edge cases stay consistent:
    timeouts and spawn failures become readable messages instead of leaking
    raw exceptions, output is decoded defensively, and stderr is only used
    when the CLI printed nothing on stdout (agent CLIs emit startup warnings
    there, which must not be mistaken for the model's answer).
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except FileNotFoundError:
        return False, f"{cmd[0]} not found on PATH"
    except Exception as exc:
        return False, str(exc)

    stdout = _strip_noise(proc.stdout or "")
    stderr = _strip_noise(proc.stderr or "")
    if proc.returncode == 0:
        return True, stdout or stderr
    return False, stderr or stdout or f"exited with code {proc.returncode}"


def count_active_cli_instances(
    binary_name: str, daemon_patterns: list[str] | None = None
) -> int:
    """Count running interactive CLI instances of binary_name."""
    if not binary_name:
        return 0
    patterns = daemon_patterns or []
    my_pid = os.getpid()
    parent_pid = os.getppid()
    try:
        res = subprocess.run(
            ["ps", "-eo", "pid,args"],
            capture_output=True,
            text=True,
            timeout=1.5,
        )
        count = 0
        for line in res.stdout.splitlines()[1:]:
            parts = line.strip().split(None, 1)
            if not parts or len(parts) < 2:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            if pid in (my_pid, parent_pid):
                continue
            cmdline = parts[1]
            if "xpx" in cmdline or "pytest" in cmdline:
                continue
            cmd_tokens = cmdline.split()
            if not cmd_tokens:
                continue
            first_cmd = cmd_tokens[0]
            matches_binary = (
                first_cmd == binary_name
                or first_cmd.endswith("/" + binary_name)
                or any(
                    t == binary_name or t.endswith("/" + binary_name)
                    for t in cmd_tokens[:3]
                )
            )
            if not matches_binary:
                continue
            if any(dp in cmdline for dp in patterns):
                continue
            count += 1
        return count
    except Exception:
        return 0


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
    effort: str | None = None
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
            "pi": [bin_path or "pi", "update"],
        }
        if bin_path and self.binary_name in native_cmds:
            cmd = native_cmds[self.binary_name]
            if dry_run:
                return True, f"would execute: {' '.join(cmd)}"
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
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
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
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

        When `spec` is provided the probe must exercise *that* provider rather
        than whatever the client currently has configured, and it must not
        modify the user's real configuration. Adapters that cannot redirect a
        single request return a clear "unsupported" result instead of silently
        probing the wrong provider.

        Returns (success, stdout/summary or error message).
        """
        pass

    def _probe_env_for_spec(
        self, spec: MergedProviderSpec | None
    ) -> dict[str, str] | None:
        """Return extra env vars that point the client at `spec` for one run.

        Returning None means this adapter has no isolation mechanism, so a
        provider-scoped probe cannot be honored safely.
        """
        return None

    def refresh_catalog(self, provider_name: str | None = None) -> bool:
        """Refresh model catalog in native files if this client is active."""
        return False

    def refresh_daemon(self, force: bool = False) -> tuple[bool, str]:
        """Refresh or reload background daemon if active and idle.

        Returns (refreshed: bool, message: str).
        When active interactive sessions exist and force=False,
        returns (False, busy_message) to protect ongoing work.
        """
        return False, ""
