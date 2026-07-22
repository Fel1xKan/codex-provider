from __future__ import annotations

import json
from pathlib import Path

import json5
import pytest

import opencode_provider as op


@pytest.fixture
def opencode_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_dir = tmp_path / ".config" / "opencode"
    data_dir = tmp_path / ".local" / "share" / "opencode"
    state_dir = tmp_path / ".local" / "state" / "opencode"
    config_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    monkeypatch.setattr(op, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(op, "DATA_DIR", data_dir)
    monkeypatch.setattr(op, "STATE_DIR", state_dir)
    monkeypatch.setattr(op, "AUTH_PATH", data_dir / "auth.json")
    monkeypatch.setattr(op, "MODEL_STATE_PATH", state_dir / "model.json")
    monkeypatch.setattr(op, "LOCK_PATH", state_dir / "opencode-provider.lock")
    return config_dir


def write_config(path: Path, suffix: str = ".json") -> Path:
    config = path / f"opencode{suffix}"
    config.write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "share": "disabled",
                "provider": {
                    "alpha": {
                        "name": "Alpha",
                        "npm": "@ai-sdk/openai",
                        "options": {
                            "baseURL": "https://alpha.example.com/v1",
                            "apiKey": "placeholder-secret",
                        },
                        "models": {"gpt-5": {"name": "GPT 5"}},
                    },
                    "beta": {
                        "name": "Beta",
                        "models": {
                            "model-a": {"name": "Model A"},
                            "model-b": {"name": "Model B"},
                        },
                    },
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return config


def test_switch_single_model_preserves_config_and_secret(
    opencode_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(opencode_paths)
    before = json.loads(config.read_text(encoding="utf-8"))

    assert op.main(["switch", "alpha"]) == 0

    after = json.loads(config.read_text(encoding="utf-8"))
    assert after["model"] == "alpha/gpt-5"
    assert after["provider"] == before["provider"]
    assert after["share"] == "disabled"
    assert "placeholder-secret" not in capsys.readouterr().out


def test_switch_explicit_model_and_reuse_model_id(
    opencode_paths: Path,
) -> None:
    config = write_config(opencode_paths)

    assert op.main(["switch", "beta", "--model", "model-b"]) == 0
    assert json.loads(config.read_text())["model"] == "beta/model-b"

    data = json.loads(config.read_text())
    data["provider"]["gamma"] = {"models": {"model-b": {}}}
    config.write_text(json.dumps(data, indent=2) + "\n")
    assert op.main(["switch", "gamma"]) == 0
    assert json.loads(config.read_text())["model"] == "gamma/model-b"


def test_switch_requires_model_when_noninteractive_and_ambiguous(
    opencode_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(opencode_paths)

    assert op.main(["switch", "beta"]) == 1
    assert "has multiple models; pass --model" in capsys.readouterr().err


def test_switch_dry_run_does_not_write(
    opencode_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(opencode_paths)
    before = config.read_bytes()

    assert op.main(["switch", "alpha", "--dry-run"]) == 0

    assert config.read_bytes() == before
    assert not op.STATE_DIR.exists()
    assert "would switch default model" in capsys.readouterr().out


def test_switch_rejects_disabled_provider(
    opencode_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(opencode_paths)
    data = json.loads(config.read_text())
    data["disabled_providers"] = ["alpha"]
    config.write_text(json.dumps(data, indent=2) + "\n")

    assert op.main(["switch", "alpha"]) == 1
    assert "excluded by enabled_providers or disabled_providers" in (
        capsys.readouterr().err
    )


def test_jsonc_switch_preserves_comments_and_trailing_comma(
    opencode_paths: Path,
) -> None:
    config = opencode_paths / "opencode.jsonc"
    config.write_text(
        """{
  // Keep this user setting.
  "share": "disabled",
  "provider": {
    "alpha": {
      "models": {
        "gpt-5": {},
      },
    },
  },
}
""",
        encoding="utf-8",
    )

    assert op.main(["switch", "alpha"]) == 0

    updated = config.read_text(encoding="utf-8")
    assert "// Keep this user setting." in updated
    assert json5.loads(updated)["model"] == "alpha/gpt-5"


def test_switch_replaces_existing_model_without_reformatting(
    opencode_paths: Path,
) -> None:
    config = write_config(opencode_paths, ".jsonc")
    text = config.read_text(encoding="utf-8")
    text = text.replace(
        '  "share": "disabled",',
        '  // Default route.\n  "model": "alpha/gpt-5",\n  "share": "disabled",',
    )
    config.write_text(text, encoding="utf-8")

    assert op.main(["switch", "beta", "--model", "model-a"]) == 0

    updated = config.read_text(encoding="utf-8")
    assert "// Default route." in updated
    assert json5.loads(updated)["model"] == "beta/model-a"


def test_list_reports_models_auth_and_active_provider(
    opencode_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(opencode_paths)
    data = json.loads(config.read_text())
    data["model"] = "beta/model-a"
    config.write_text(json.dumps(data, indent=2) + "\n")
    op.AUTH_PATH.write_text(
        json.dumps({"beta": {"type": "api", "key": "placeholder-beta"}}),
        encoding="utf-8",
    )

    assert op.main(["list"]) == 0

    output = capsys.readouterr().out
    assert "  alpha" in output
    assert "* beta" in output
    assert "models=1" in output
    assert "models=2" in output
    assert output.count("auth=yes") == 2
    assert "placeholder-secret" not in output
    assert "placeholder-beta" not in output


def test_status_uses_first_valid_recent_model(
    opencode_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_config(opencode_paths)
    op.STATE_DIR.mkdir(parents=True)
    op.MODEL_STATE_PATH.write_text(
        json.dumps(
            {
                "recent": [
                    {"providerID": "missing", "modelID": "unknown"},
                    {"providerID": "beta", "modelID": "model-b"},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert op.main(["status"]) == 0

    output = capsys.readouterr().out
    assert "default provider: beta" in output
    assert "default model: model-b" in output
    assert "model source: recent model" in output
    assert "* beta" in output


class ModelsResponse:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit=-1):
        return self.payload if limit < 0 else self.payload[:limit]


def test_models_sync_adds_missing_ids_and_preserves_existing_config(
    opencode_paths: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write_config(opencode_paths)
    monkeypatch.setattr(
        op.urllib.request,
        "urlopen",
        lambda request, timeout: ModelsResponse(
            json.dumps({"data": [{"id": "gpt-5"}, {"id": "gpt-5-new"}]}).encode()
        ),
    )

    assert op.main(["models", "sync", "alpha"]) == 0

    data = json5.loads(config.read_text())
    assert data["provider"]["alpha"]["models"]["gpt-5"]["name"] == "GPT 5"
    assert data["provider"]["alpha"]["models"]["gpt-5-new"] == {}


def test_models_list_uses_auth_json_without_printing_secret(
    opencode_paths: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_config(opencode_paths)
    config = json.loads((opencode_paths / "opencode.json").read_text())
    config["provider"]["beta"]["options"] = {"baseURL": "https://beta.example.com/v1"}
    (opencode_paths / "opencode.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )
    op.AUTH_PATH.write_text(
        json.dumps({"beta": {"type": "api", "key": "placeholder-key"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        op.urllib.request,
        "urlopen",
        lambda request, timeout: ModelsResponse(
            json.dumps({"data": [{"id": "model-c"}]}).encode()
        ),
    )

    assert op.main(["models", "list", "beta"]) == 0

    output = capsys.readouterr().out
    assert "- model-c" in output
    assert "placeholder-key" not in output


def test_switch_reports_sync_command_for_empty_provider(
    opencode_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(opencode_paths)
    data = json.loads(config.read_text())
    data["provider"]["empty"] = {"options": {"baseURL": "https://example.com"}}
    config.write_text(json.dumps(data, indent=2) + "\n")

    assert op.main(["switch", "empty"]) == 1
    assert "models sync empty" in capsys.readouterr().err


def test_test_command_matches_codex_provider_shape(
    opencode_paths: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(opencode_paths)
    calls = []

    def fake_models_test(*args, **kwargs):
        calls.append((*args, kwargs))
        return 0

    monkeypatch.setattr(op, "run_models_test", fake_models_test)

    assert op.main(["test", "alpha", "--timeout", "5"]) == 0
    assert calls[0][0] == "alpha"
    assert calls[0][1] == "https://alpha.example.com/v1"
    assert calls[0][2] == "placeholder-secret"
    assert calls[0][3] == 5.0
    assert calls[0][5]["program"] == "opencode-provider"


def test_ping_command_matches_codex_provider_shape(
    opencode_paths: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(opencode_paths)
    captured = []

    class Result:
        returncode = 0

    monkeypatch.setattr(op.shutil, "which", lambda name: "/usr/bin/opencode")
    monkeypatch.setattr(
        op.subprocess,
        "run",
        lambda command, stdin, timeout: (
            captured.append((command, stdin, timeout)) or Result()
        ),
    )

    assert op.main(["ping", "alpha", "--timeout", "7", "--prompt", "hello"]) == 0
    assert captured == [
        (
            ["/usr/bin/opencode", "run", "--model", "alpha/gpt-5", "hello"],
            op.subprocess.DEVNULL,
            7.0,
        )
    ]


def test_delete_provider_preserves_other_config(
    opencode_paths: Path,
) -> None:
    config = write_config(opencode_paths)

    assert op.main(["delete", "beta"]) == 0

    data = json5.loads(config.read_text())
    assert set(data["provider"]) == {"alpha"}
    assert data["share"] == "disabled"


def test_delete_full_removes_auth_entry(
    opencode_paths: Path,
) -> None:
    write_config(opencode_paths)
    op.AUTH_PATH.write_text(
        json.dumps(
            {
                "alpha": {"type": "api", "key": "alpha-key"},
                "beta": {"type": "api", "key": "beta-key"},
            }
        ),
        encoding="utf-8",
    )

    assert op.main(["delete", "beta", "--full"]) == 0

    auth = json.loads(op.AUTH_PATH.read_text())
    assert set(auth) == {"alpha"}


def test_delete_rejects_current_provider(
    opencode_paths: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = write_config(opencode_paths)
    data = json.loads(config.read_text())
    data["model"] = "beta/model-a"
    config.write_text(json.dumps(data, indent=2) + "\n")

    assert op.main(["delete", "beta"]) == 1
    assert "cannot delete the current provider" in capsys.readouterr().err


def test_delete_dry_run_does_not_write(
    opencode_paths: Path,
) -> None:
    config = write_config(opencode_paths)
    before = config.read_bytes()

    assert op.main(["delete", "beta", "--dry-run"]) == 0

    assert config.read_bytes() == before
    assert not op.STATE_DIR.exists()
