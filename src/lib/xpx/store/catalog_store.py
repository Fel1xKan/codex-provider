from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lib.common.common_store import atomic_write_bytes, ensure_private_dir
from lib.common.errors import SwitchError
from lib.xpx.store import get_xpx_home, xpx_lock
from lib.xpx.store.provider_store import validate_provider_name


@dataclass
class ModelMetadata:
    """Metadata and capability specification for a specific model."""

    id: str
    display_name: str
    context_window: int = 128000
    max_output_tokens: int = 8192
    supported_reasoning_levels: list[str] = field(default_factory=list)
    default_reasoning_level: str | None = None
    input_modalities: list[str] = field(default_factory=lambda: ["text"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "supported_reasoning_levels": list(self.supported_reasoning_levels),
            "default_reasoning_level": self.default_reasoning_level,
            "input_modalities": list(self.input_modalities),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelMetadata:
        if not isinstance(data, dict):
            raise SwitchError("invalid model metadata payload: expected dict")
        model_id = str(data.get("id", ""))
        display_name = str(data.get("display_name") or model_id)
        return cls(
            id=model_id,
            display_name=display_name,
            context_window=int(data.get("context_window", 128000)),
            max_output_tokens=int(data.get("max_output_tokens", 8192)),
            supported_reasoning_levels=list(
                data.get("supported_reasoning_levels") or []
            ),
            default_reasoning_level=data.get("default_reasoning_level") or None,
            input_modalities=list(data.get("input_modalities") or ["text"]),
        )


@dataclass
class ProviderCatalog:
    """Catalog of discovered/cached models for a specific provider."""

    provider: str
    updated_at: str
    models: dict[str, ModelMetadata] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "updated_at": self.updated_at,
            "models": {k: v.to_dict() for k, v in self.models.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderCatalog:
        if not isinstance(data, dict):
            raise SwitchError("invalid catalog payload: expected dict")
        provider = validate_provider_name(str(data.get("provider", "")))
        updated_at = str(data.get("updated_at", ""))
        raw_models = data.get("models") or {}
        models = {
            k: ModelMetadata.from_dict(v)
            for k, v in raw_models.items()
            if isinstance(v, dict)
        }
        return cls(provider=provider, updated_at=updated_at, models=models)


class CatalogStore:
    """Manages cached provider model catalogs under ~/.xpx/catalogs/."""

    def __init__(self, home: Path | None = None) -> None:
        self._home = home or get_xpx_home()

    @property
    def catalogs_dir(self) -> Path:
        p = self._home / "catalogs"
        ensure_private_dir(p)
        return p

    def catalog_path(self, provider: str) -> Path:
        valid_name = validate_provider_name(provider)
        return self.catalogs_dir / f"{valid_name}.json"

    def get(self, provider: str) -> ProviderCatalog | None:
        path = self.catalog_path(provider)
        if not path.is_file():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return ProviderCatalog.from_dict(data)
        except (OSError, json.JSONDecodeError, SwitchError) as exc:
            raise SwitchError(
                f"failed to load catalog for provider '{provider}': {exc}"
            ) from exc

    def save(self, catalog: ProviderCatalog) -> None:
        validate_provider_name(catalog.provider)
        if not catalog.updated_at:
            catalog.updated_at = datetime.now(UTC).isoformat()
        path = self.catalog_path(catalog.provider)
        payload = (json.dumps(catalog.to_dict(), indent=2) + "\n").encode("utf-8")
        with xpx_lock():
            atomic_write_bytes(path, payload)

    def delete(self, provider: str) -> bool:
        path = self.catalog_path(provider)
        with xpx_lock():
            if path.is_file():
                path.unlink()
                return True
        return False
