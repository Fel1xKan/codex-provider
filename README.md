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
./codex-provider auth detail
./codex-provider auth detail anyrouter
EDITOR=vim ./codex-provider auth edit
EDITOR=vim ./codex-provider auth edit anyrouter
./codex-provider config detail
./codex-provider config detail anyrouter
EDITOR=vim ./codex-provider config edit
EDITOR=vim ./codex-provider config edit anyrouter
./codex-provider doctor
./codex-provider switch
./codex-provider switch anyrouter
./codex-provider switch krill --dry-run
./codex-provider test
./codex-provider test ggniao
./codex-provider test https://api.example.com sk-your-key
printf '%s\n' 'sk-your-key' | ./codex-provider test https://api.example.com --api-key-stdin
./codex-provider ping
./codex-provider ping ggniao
./codex-provider p ggniao
./codex-provider add https://api.example.com sk-your-key
printf '%s\n' 'sk-your-key' | ./codex-provider add https://api.example.com --api-key-stdin
./codex-provider add https://api.example.com sk-your-key --provider foo
./codex-provider delete foo
./codex-provider delete foo --full
```

## Optional Install

```bash
chmod +x ./codex-provider ./codex_provider.py
ln -sf "$(pwd)/codex-provider" ~/.local/bin/codex-provider
```

## Build

```text
python build.py
py -3 build.py        # Windows, if using the Python launcher
./build.sh            # Optional macOS/Linux wrapper
.\build.cmd           # Optional Windows cmd.exe/PowerShell wrapper
```

The build script uses the `PYTHON` environment variable when set, then a local
`.venv` (`.venv/bin/python` or `.venv/Scripts/python.exe`) when present, and
falls back to the interpreter running `build.py`. It rebuilds the PyInstaller
binary from `codex-provider-bin.spec` and verifies that the generated binary
starts successfully. On Windows the output is `dist/codex-provider-bin.exe`;
on macOS and Linux it is `dist/codex-provider-bin`.

## Tool Config

```toml
codex_dir = "/home/you/.codex"

[model_providers.anyrouter]
base_url = "https://anyrouter.top/v1"
name = "Any Router"
requires_openai_auth = true
wire_api = "responses"
supports_websockets = false
extra_headers = { x_team = "infra" }
```

## Notes

- `doctor` will create `~/.codex-provider/`, `~/.codex-provider/config.toml`, and `~/.codex-provider/auth/` if they do not exist.
- `doctor --fix` archives legacy `~/.codex/auth.json.*` files to `*.bak.<timestamp>` instead of deleting them.
- `add <base-url> <api-key>` also auto-initializes `~/.codex-provider` on a fresh machine, derives the provider name from the base URL unless `--provider` is set, writes `requires_openai_auth = true`, defaults `wire_api = "responses"`, and creates `~/.codex-provider/auth/<provider>.json` with `OPENAI_API_KEY`. Host-only URLs such as `https://api.example.com` are normalized to `https://api.example.com/v1`; URLs that already include a path are kept as provided. Use `--api-key-stdin` when you do not want the key in shell history.
- If you manually add custom provider keys in `~/.codex-provider/config.toml`, `switch` will carry the whole provider block into `~/.codex/config.toml`.
- `switch` with no argument opens an interactive picker when stdin/stdout are TTYs: use Up/Down to move, Enter to select, Esc to cancel, Ctrl+C to abort. Without a TTY it errors and asks for a provider name.
- `auth detail` defaults to the runtime `~/.codex/auth.json`; `auth detail <provider>` prints `~/.codex-provider/auth/<provider>.json`.
- `auth edit` defaults to the runtime `~/.codex/auth.json`; `auth edit <provider>` opens `~/.codex-provider/auth/<provider>.json`.
- `config detail` prints a provider block from `~/.codex-provider/config.toml`; without an argument it defaults to the current provider.
- `config edit` opens `~/.codex-provider/config.toml`; with `<provider>` it first validates that provider exists.
- `test` requests `<base_url>/models` to verify that a base URL and API key work. Without an argument it tests the current provider from config; with `<provider>` it tests that provider; with `<base-url> <api-key>` or `<base-url> --api-key-stdin` it tests direct input without writing config.
- `ping` / `p` tests one provider with a minimal `codex exec` prompt `say hi`. Without an argument it tests the current provider; with `<provider>` it switches to that provider first and tests only that provider.
- `delete <provider>` removes the provider config and keeps the auth snapshot by default. `delete <provider> --full` also removes the auth snapshot, and can clean up a leftover auth snapshot even when the provider config was already deleted.
- Ctrl+C (SIGINT) during any long-running command (`ping`, `test`, `edit`, interactive `switch`) exits cleanly with code 130 instead of printing a traceback.
