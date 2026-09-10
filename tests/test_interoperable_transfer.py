from __future__ import annotations

import pytest

from lib.common.transfer import build_interoperable_export


@pytest.mark.parametrize(
    ("target_tool", "expected_type"),
    (
        ("cpx", "codex-provider"),
        ("opx", "opencode-provider"),
        ("clpx", "claude-provider"),
        ("cupx", "cursor-provider"),
    ),
)
def test_interoperable_export_uses_the_target_import_format(
    target_tool: str, expected_type: str
) -> None:
    exported = build_interoperable_export(
        target_tool,
        "alpha",
        {
            "alpha": {
                "base_url": "https://alpha.example.com/v1",
                "name": "Alpha",
                "api_key": "placeholder-alpha",
                "models": ["gpt-5"],
                "model": "gpt-5",
            }
        },
        active_model="gpt-5",
    )

    assert exported["type"] == expected_type
    assert exported["version"] == 1

    if target_tool == "cpx":
        provider = exported["providers"]["alpha"]
        assert provider["config"]["base_url"] == "https://alpha.example.com/v1"
        assert provider["auth"]["OPENAI_API_KEY"] == "placeholder-alpha"
    elif target_tool == "opx":
        provider = exported["providers"]["alpha"]
        assert provider["config"]["options"]["baseURL"] == (
            "https://alpha.example.com/v1"
        )
        assert provider["auth"]["key"] == "placeholder-alpha"
        assert exported["current_provider"] == "alpha"
        assert exported["current_model"] == "gpt-5"
    elif target_tool == "clpx":
        provider = exported["providers"]["alpha"]
        assert provider["config"]["base_url"] == "https://alpha.example.com/v1"
        assert provider["auth"]["ANTHROPIC_AUTH_TOKEN"] == "placeholder-alpha"
    else:
        assert "accounts" not in exported
        assert "current" not in exported
        assert exported["current_provider"] == "alpha"
        provider = exported["providers"]["alpha"]
        assert provider["base_url"] == "https://alpha.example.com/v1"
        assert provider["api_key"] == "placeholder-alpha"
