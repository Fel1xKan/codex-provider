from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        integer = int(value)
        return integer if integer > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            integer = int(text)
            return integer if integer > 0 else None
    return None


def _lookup(record: Mapping[str, Any], paths: tuple[tuple[str, ...], ...]) -> Any:
    for path in paths:
        value: Any = record
        for key in path:
            if not isinstance(value, Mapping):
                value = None
                break
            value = value.get(key)
        if value is not None:
            return value
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list | tuple):
        values = value
    else:
        return []
    return [item.strip() for item in values if isinstance(item, str) and item.strip()]


def _input_modalities(record: Mapping[str, Any]) -> list[str]:
    raw = _lookup(
        record,
        (
            ("input_modalities",),
            ("inputModalities",),
            ("modalities",),
            ("architecture", "input_modalities"),
            ("architecture", "inputModalities"),
            ("architecture", "modalities"),
            ("supported_modalities",),
            ("supportedModalities",),
        ),
    )
    values = _string_list(raw)
    normalized: list[str] = []
    for value in values:
        lower = value.lower()
        if lower in {"image", "images", "vision", "image_url", "image_url_input"}:
            name = "image"
        elif lower in {"text", "texts"}:
            name = "text"
        elif lower in {"audio", "video", "file"}:
            name = lower
        else:
            name = value
        if name not in normalized:
            normalized.append(name)

    capabilities = record.get("capabilities")
    if isinstance(capabilities, Mapping):
        image_input = capabilities.get("image_input")
        if (
            isinstance(image_input, Mapping)
            and image_input.get("supported") is True
            and "image" not in normalized
        ):
            normalized.append("image")
        pdf_input = capabilities.get("pdf_input")
        if (
            isinstance(pdf_input, Mapping)
            and pdf_input.get("supported") is True
            and "file" not in normalized
        ):
            normalized.append("file")
        if normalized and "text" not in normalized:
            normalized.insert(0, "text")
    return normalized


def _supports_reasoning(record: Mapping[str, Any]) -> bool | None:
    for path in (
        ("reasoning",),
        ("supports_reasoning",),
        ("supportsReasoning",),
        ("reasoning_supported",),
        ("reasoningSupported",),
        ("thinking",),
        ("supports_thinking",),
        ("supportsThinking",),
        ("capabilities", "thinking", "supported"),
        ("capabilities", "effort", "supported"),
    ):
        value = _lookup(record, (path,))
        if isinstance(value, bool):
            return value

    supported = _lookup(
        record,
        (
            ("supported_parameters",),
            ("supportedParameters",),
            ("capabilities", "supported_parameters"),
            ("capabilities", "supportedParameters"),
        ),
    )
    names = {item.lower() for item in _string_list(supported)}
    if names & {
        "reasoning",
        "reasoning_effort",
        "reasoning_effort_level",
        "reasoning_content",
        "thinking",
    }:
        return True
    return None


def extract_model_metadata(record: Mapping[str, Any]) -> dict[str, Any]:
    """Extract only explicit, provider-supplied model capability metadata.

    Generic /models APIs are not required to expose these fields. Callers must
    keep their backend defaults when a value is absent and must not infer
    capabilities from a model ID.
    """

    metadata: dict[str, Any] = {}
    display_name = _lookup(
        record,
        (
            ("display_name",),
            ("displayName",),
            ("name",),
            ("title",),
        ),
    )
    if isinstance(display_name, str) and display_name.strip():
        metadata["display_name"] = display_name.strip()

    context_window = _positive_int(
        _lookup(
            record,
            (
                ("context_window",),
                ("contextWindow",),
                ("context_length",),
                ("contextLength",),
                ("max_context_length",),
                ("maxContextLength",),
                ("max_input_tokens",),
                ("maxInputTokens",),
                ("input_token_limit",),
                ("inputTokenLimit",),
                ("limits", "context"),
                ("limits", "context_window"),
                ("metadata", "context_window"),
                ("metadata", "contextWindow"),
                ("metadata", "context_length"),
                ("top_provider", "context_length"),
                ("top_provider", "context_window"),
            ),
        )
    )
    if context_window is not None:
        metadata["context_window"] = context_window

    max_output_tokens = _positive_int(
        _lookup(
            record,
            (
                ("max_output_tokens",),
                ("maxOutputTokens",),
                ("max_tokens",),
                ("maxTokens",),
                ("max_completion_tokens",),
                ("maxCompletionTokens",),
                ("output_token_limit",),
                ("outputTokenLimit",),
                ("limits", "output"),
                ("limits", "max_output_tokens"),
                ("metadata", "max_output_tokens"),
                ("metadata", "maxOutputTokens"),
                ("top_provider", "max_completion_tokens"),
                ("top_provider", "max_output_tokens"),
            ),
        )
    )
    if max_output_tokens is not None:
        metadata["max_output_tokens"] = max_output_tokens

    input_modalities = _input_modalities(record)
    if input_modalities:
        metadata["input_modalities"] = input_modalities

    supports_reasoning = _supports_reasoning(record)
    if supports_reasoning is not None:
        metadata["supports_reasoning"] = supports_reasoning

    return metadata


def model_record_map(result: Any) -> dict[str, dict[str, Any]]:
    """Return model records from a metadata-aware result or a plain ID list."""

    records = getattr(result, "records", None)
    if isinstance(records, Mapping):
        normalized = {
            model_id: dict(record)
            for model_id, record in records.items()
            if isinstance(model_id, str) and isinstance(record, Mapping)
        }
        if normalized:
            return normalized

    return {
        model_id: {"id": model_id}
        for model_id in result
        if isinstance(model_id, str) and model_id
    }
