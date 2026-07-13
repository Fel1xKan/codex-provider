# codex-provider

`codex-provider` is a Python 3.11+ CLI for managing Codex model providers and
their matching `auth.json` snapshots.

It keeps the complete provider registry outside the Codex runtime config,
copies only the active provider into `~/.codex/config.toml`, and switches the
matching auth snapshot together with it.

## Safety properties

- Credential values are never printed by `auth detail`.
- API keys are read from a hidden prompt or standard input, never accepted as
  normal command arguments.
- Provider names are validated before they are used in file paths.
- Provider state changes are protected by a process lock.
- Multi-file `add`, `delete`, and `switch` changes roll back when a write fails.
- On POSIX systems, state directories use mode `0700` and auth files use
  `0600`.
- TOML updates preserve unrelated settings, comments, and supported custom
  provider values.
- `ping <provider>` activates that provider only for the duration of the ping
  and restores the original runtime state afterward.

## Installation

The recommended installation uses `pipx`:

```bash
pipx install .
codex-provider --version
```

For development:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m pytest
```

On Windows, use `.venv\Scripts\python.exe` in place of
`./.venv/bin/python`.

The repository launcher uses `.venv/bin/python` when available and otherwise
falls back to `python3`:

```bash
./codex-provider --help
```

## Commands

```bash
codex-provider list
codex-provider status

codex-provider auth detail
codex-provider auth detail anyrouter
EDITOR=vim codex-provider auth edit
EDITOR="code --wait" codex-provider auth edit anyrouter

codex-provider config detail
codex-provider config detail anyrouter
EDITOR=vim codex-provider config edit anyrouter

codex-provider doctor
codex-provider doctor --fix

codex-provider switch
codex-provider switch anyrouter
codex-provider switch krill --dry-run

codex-provider test
codex-provider test ggniao
codex-provider test https://api.example.com
printf '%s\n' "$PROVIDER_API_KEY" | \
  codex-provider test https://api.example.com --api-key-stdin

codex-provider ping
codex-provider ping ggniao
codex-provider ping ggniao --model gpt-5

codex-provider add https://api.example.com
printf '%s\n' "$PROVIDER_API_KEY" | \
  codex-provider add https://api.example.com --api-key-stdin
codex-provider add https://api.example.com --provider foo --name "Example"

codex-provider delete foo
codex-provider delete foo --full
```

When `add` or a direct URL `test` runs in an interactive terminal, it prompts
for the API key without echoing it. Use `--api-key-stdin` for automation. Do
not put API keys directly in a command line because command arguments may be
stored in shell history or exposed through process inspection.

## State layout

```text
~/.codex-provider/
├── .lock
├── config.toml
└── auth/
    ├── anyrouter.json
    └── example.json

~/.codex/
├── config.toml
└── auth.json
```

- `~/.codex-provider/config.toml` contains the full provider registry.
- `~/.codex-provider/auth/<provider>.json` contains each provider auth
  snapshot.
- `~/.codex/config.toml` contains only the active provider block.
- `~/.codex/auth.json` contains the active auth snapshot.

Before a persistent switch, the current runtime auth is saved back to its
provider snapshot. The target auth and runtime config are then committed as one
recoverable operation.

## Tool config

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

Provider names must match `[A-Za-z0-9_-]+`. Custom provider values are carried
into the active runtime block. Host-only HTTP(S) URLs are normalized to `/v1`.
URLs containing user credentials, query parameters, fragments, or non-HTTP(S)
schemes are rejected.

## Command behavior

- `auth detail` reports the auth path, field names, value types, and whether a
  field is configured. It never prints credential values.
- `auth edit` validates the edited JSON and restores the original file if the
  edit is invalid. POSIX permissions are reset to `0600` after a valid edit.
- `config edit` validates the edited registry and restores the original file
  if the edit is invalid. `$VISUAL` and `$EDITOR` may include arguments such as
  `code --wait`.
- `config detail` redacts values whose keys look credential-related, including
  authorization headers, tokens, passwords, cookies, secrets, and API keys.
- `switch --dry-run`, `add --dry-run`, and `delete --dry-run` do not write
  state. On a fresh HOME, they do not create tool directories or lock files.
- `test` calls `<base_url>/models`, limits the response body to 2 MiB, and
  requires an OpenAI-compatible JSON object with a `data` array.
- `ping <provider>` holds the provider-state lock, temporarily updates runtime
  config/auth, runs an ephemeral `codex exec`, and restores the original files
  even when the command fails or is interrupted.
- `doctor` checks registry/runtime consistency, auth JSON validity, missing
  snapshots, legacy snapshots, and POSIX permissions.
- `doctor --fix` archives legacy `~/.codex/auth.json.*` files and repairs
  insecure POSIX permissions. It does not invent missing provider data.
- On Unix-like terminals, `switch` without a provider uses an arrow-key menu.
  On Windows, it uses a numbered prompt. In non-interactive environments, pass
  the provider name explicitly.

## Build

The standalone binary is built with the pinned PyInstaller version in
`requirements.txt`:

```bash
python build.py
./build.sh
```

On Windows:

```bat
py -3 build.py
build.cmd
```

The output is `dist/codex-provider-bin` on macOS/Linux and
`dist/codex-provider-bin.exe` on Windows. `build.py` verifies the generated
binary with `--help` after building and writes a matching `.sha256` checksum.
UPX compression is disabled so the build does not vary based on whether UPX is
installed on the build host. CI tests Python 3.11 through 3.13 on Linux, macOS,
and Windows, builds a standalone binary on all three platforms, and uploads the
binary plus checksum as workflow artifacts.

## Validation

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest
python build.py
```
