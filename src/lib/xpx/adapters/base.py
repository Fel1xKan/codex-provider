from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TargetStatus:
    """Current status of a target client for reporting in xpx status."""

    installed: bool
    active_type: str  # "provider" | "account" | "official" | "none"
    active_name: str
    active_model: str | None = None
    config_path: str = ""
    extra_summary: str = ""


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
    supported_protocols: list[str] = ["openai"]
    supports_fast: bool = False
    supports_web_search: bool = False
    supports_wire_api: bool = False

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
