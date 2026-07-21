from __future__ import annotations

import io
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
from conftest import IsolatedPaths

import codex_provider as cp
from codex_provider_lib import network
from codex_provider_lib.platform import split_command


class FakeResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        if limit < 0:
            return self.payload
        return self.payload[:limit]


def test_add_rejects_positional_api_key_without_echoing_it(
    isolated_paths: IsolatedPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "placeholder-never-echo-this"
    assert cp.main(["add", "https://example.com", secret]) == 1
    output = capsys.readouterr()
    combined = output.out + output.err
    assert secret not in combined
    assert "must not be passed as a command argument" in combined


def test_add_name_is_written_as_provider_display_name(
    isolated_paths: IsolatedPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cp, "read_api_key", lambda from_stdin: "placeholder-key")

    assert (
        cp.main(
            [
                "add",
                "https://api.example.com",
                "--provider",
                "example-id",
                "--name",
                "Example Display Name",
            ]
        )
        == 0
    )

    data = tomllib.loads(isolated_paths.tool_config.read_text(encoding="utf-8"))
    assert data["model_providers"]["example-id"]["name"] == ("Example Display Name")


def test_direct_test_rejects_positional_api_key_without_echoing_it(
    isolated_paths: IsolatedPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "placeholder-never-echo-this"
    assert cp.main(["test", "https://example.com", secret]) == 1
    output = capsys.readouterr()
    combined = output.out + output.err
    assert secret not in combined


@pytest.mark.parametrize(
    "value",
    [
        "ftp://example.com",
        "https://user:pass@example.com",
        "https://example.com/v1?token=value",
        "https://example.com/v1#fragment",
    ],
)
def test_base_url_rejects_unsafe_or_ambiguous_values(value: str) -> None:
    with pytest.raises(cp.SwitchError):
        cp.normalize_base_url(value)


def test_models_url_is_built_structurally() -> None:
    assert network.models_url("https://example.com") == (
        "https://example.com/v1/models"
    )
    assert network.models_url("https://example.com/custom/") == (
        "https://example.com/custom/models"
    )


def test_models_test_rejects_non_openai_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        network.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(json.dumps({"ok": True}).encode()),
    )
    result = network.run_models_test(
        "direct",
        "https://example.com/v1",
        "placeholder-key",
        1,
        None,
    )
    assert result == 1
    assert "not OpenAI-compatible" in capsys.readouterr().out


def test_models_test_rejects_non_utf8_response(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        network.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(b"\xff\xfe"),
    )
    result = network.run_models_test(
        "direct",
        "https://example.com/v1",
        "placeholder-key",
        1,
        None,
    )
    assert result == 1
    assert "not valid JSON" in capsys.readouterr().out


def test_models_test_limits_response_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = b"x" * (network.MAX_HTTP_BODY_BYTES + 1)
    monkeypatch.setattr(
        network.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(payload),
    )
    result = network.run_models_test(
        "direct",
        "https://example.com/v1",
        "placeholder-key",
        1,
        None,
    )
    assert result == 1
    assert "response body exceeds" in capsys.readouterr().out


def test_error_summary_redacts_api_key() -> None:
    secret = "placeholder-secret-key"
    payload = json.dumps({"error": {"message": f"bad key: {secret}"}}).encode()
    summary = network.summarize_response_error(payload, secret)
    assert secret not in summary
    assert "[REDACTED]" in summary


def test_plain_text_error_summary_redacts_api_key() -> None:
    secret = "placeholder-secret-key"
    summary = network.summarize_response_error(f"bad key: {secret}".encode(), secret)
    assert secret not in summary
    assert "[REDACTED]" in summary


def test_read_api_key_requires_stdin_flag_when_not_interactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cp.sys, "stdin", io.StringIO("placeholder-key\n"))
    with pytest.raises(cp.SwitchError, match="TTY or --api-key-stdin"):
        cp.read_api_key(False)
    assert cp.read_api_key(True) == "placeholder-key"


def test_editor_command_supports_arguments() -> None:
    assert split_command("code --wait") == ["code", "--wait"]


def test_version_matches_project_metadata() -> None:
    project = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert "version" in project["project"]["dynamic"]
    assert project["tool"]["setuptools"]["dynamic"]["version"]["attr"] == (
        "codex_provider_lib.constants.VERSION"
    )


def test_auth_edit_validation_does_not_expose_invalid_contents(
    initialized_registry: IsolatedPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "placeholder-invalid-secret"

    def invalid_editor(path: Path) -> None:
        path.write_text(f"not-json {secret}", encoding="utf-8")

    monkeypatch.setattr(cp, "run_editor", invalid_editor)
    original = (initialized_registry.auth_store / "alpha.json").read_bytes()
    with pytest.raises(cp.SwitchError) as exc_info:
        cp.edit_auth("alpha")
    assert secret not in str(exc_info.value)
    assert (initialized_registry.auth_store / "alpha.json").read_bytes() == original
