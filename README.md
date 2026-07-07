# codex-provider

Lightweight CLI for switching Codex `model_provider` and matching `auth.json` profiles.

## What It Does

- Stores the full provider registry in `~/.codex-provider/config.toml`
- Stores provider auth snapshots in `~/.codex-provider/auth/*.json`
- Keeps `~/.codex/config.toml` as runtime state with only the current provider block
- Supports manual edits to provider blocks in `~/.codex-provider/config.toml`
- Switches the active top-level `model_provider`
- Copies `~/.codex-provider/auth/<provider>.json` to `~/.codex/auth.json`
- Saves the current `auth.json` back to `~/.codex-provider/auth/<current-provider>.json` before switching away
- Copies the entire selected `[model_providers.<name>]` block into `~/.codex/config.toml`
- Uses atomic writes for both files

## Commands

```bash
./codex-provider list
./codex-provider status
./codex-provider doctor
./codex-provider switch anyrouter
./codex-provider switch krill --dry-run
./codex-provider add foo --base-url https://example.com/v1
./codex-provider delete foo
./codex-provider delete foo --full
```

## Optional Install

```bash
chmod +x ./codex-provider ./codex_provider.py
ln -sf "$(pwd)/codex-provider" ~/.local/bin/codex-provider
```

## Tool Config

```toml
codex_dir = "/home/you/.codex"

[model_providers.anyrouter]
base_url = "https://anyrouter.top/v1"
name = "Any Router"
wire_api = "responses"
supports_websockets = false
extra_headers = { x_team = "infra" }
```

## Notes

- `doctor` will create `~/.codex-provider/`, `~/.codex-provider/config.toml`, and `~/.codex-provider/auth/` if they do not exist.
- `doctor --fix` archives legacy `~/.codex/auth.json.*` files to `*.bak.<timestamp>` instead of deleting them.
- `add` also auto-initializes `~/.codex-provider` on a fresh machine.
- If you manually add custom provider keys in `~/.codex-provider/config.toml`, `switch` will carry the whole provider block into `~/.codex/config.toml`.
