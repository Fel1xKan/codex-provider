# Command Reference

This document covers the `xpx` unified AI agent provider control plane. Run `xpx <command> --help` for the exact parser surface of any command.

## Command Tree Overview

```text
xpx
├── list                               --json
├── show [provider]                    --target --reveal-key
├── set <provider> [target]            --base-url --protocol --default-model
│                                      --key --key-stdin --header --name
│                                      --fast/--no-fast --wire-api
│                                      --web-search/--no-web-search --option
├── add <name> [base_url]              --key --key-stdin --default-model --protocol
├── delete <name>                      --full --dry-run
│
├── models
│   ├── sync <provider>                --force
│   ├── list [provider]                --remote
│   └── set <provider> <model>         --display-name --default --context
│                                      --max-output --effort --modalities
│                                      --overwrite
│
├── apply [target] [provider_spec] [model_arg]
│                                      --all --account --model --clear
│                                      --dry-run --no-save --header
│                                      --fast/--no-fast --wire-api
│                                      --web-search/--no-web-search
│                                      --restart-daemon
│
├── account
│   ├── login <target> [name]
│   ├── snapshot <target> <name>
│   ├── list
│   └── usage [target] [name]
│
├── status
├── doctor                             --fix
├── test [provider]                    --deep --target --model --prompt --timeout --all
│
├── agent
│   ├── list
│   ├── install [target]               --all --dry-run --force
│   └── update [target]                --all --dry-run
│
├── migrate                            --dry-run --force
├── import [file]                      --force
├── export [file]
├── upgrade                            --check --notes --dry-run
└── interactive                        (aliases: i, menu)
```

---

## 1. Provider Asset Management

### `xpx add <name> [base_url]`
Register a new API provider into the centralized store (`~/.xpx/providers/<name>.json`).

- **Arguments**:
  - `name`: Identifier containing only letters, numbers, hyphens, and underscores (`^[a-zA-Z0-9_-]+$`).
  - `base_url`: API base endpoint URL (e.g., `https://api.deepseek.com/v1`). Prompted if omitted in interactive TTY.
- **Options**:
  - `--key <text>`: API key string.
  - `--key-stdin`: Read the API key from stdin.
  - `--default-model <text>`: Primary model ID to use by default.
  - `--protocol <openai|anthropic>`: Wire protocol (default: `openai`).

```bash
# Add with interactive key entry
xpx add deepseek https://api.deepseek.com/v1 --default-model deepseek-reasoner

# Add via stdin pipe
echo "sk-secret" | xpx add openrouter https://openrouter.ai/api/v1 --key-stdin
```

### `xpx list`
List all registered providers and their active status across client targets.

- **Options**:
  - `--json`: Output as structured JSON.

```bash
xpx list
```

### `xpx show [provider]`
Inspect a provider's effective configuration, or summarize every provider.

Shows protocol, base URL, default model, a masked API key (first 4 and last 4
characters), global headers, configured target overrides, and which clients
currently have this provider active. Replaces the former `auth show` and
`config show`.

- **Options**:
  - `--target <name>`: Show only that client's overrides.
  - `--reveal-key`: Print the API key instead of masking it.

```bash
xpx show                       # summarize all providers
xpx show deepseek              # one provider, masked key
xpx show deepseek --target codex
xpx show deepseek --reveal-key
```

### `xpx delete <name>`
Delete a provider from the central store.

- **Options**:
  - `--full`: Also remove this provider's configuration from all active client targets.
  - `--dry-run`: Preview changes without deleting.

```bash
xpx delete deepseek --full
```

---

## 2. Updating a Provider (`set`)

### `xpx set <provider> [target]`
The single write surface for a provider: it creates the provider if it does not
exist, and otherwise updates whichever fields you name. This replaces the former
`rename`, `auth set`, and `config set`, which all edited the same provider object
through different commands.

Two shapes, distinguished by the optional positional target:

```bash
xpx set <provider> [options]           # edit the provider itself
xpx set <provider> <target> [options]  # edit that client's overrides
```

The target is positional rather than a `--target` flag because it reads as
"this provider, as seen by that client", and because it keeps provider fields
and per-client overrides from being mixed in one invocation.

Renaming a provider with `--name` also moves its cached model catalog and its
active-client pointers, so model metadata is not orphaned.

- **Provider fields** (no target):
  - `--base-url <url>`: Endpoint base URL.
  - `--protocol <openai|anthropic>`: Wire protocol.
  - `--default-model <model>`: Default model for this provider.
  - `--key <text>` / `--key-stdin`: Replace the API key (prompts when neither is given).
  - `--header <k=v>`: Global header (pass `k=` to remove).
  - `--name <new-name>`: Rename the provider.
- **Target overrides** (with a target):
  - `--fast` / `--no-fast`: Codex fast mode (`service_tier = "priority"`).
  - `--wire-api <chat|responses>`: Codex wire API.
  - `--web-search <true|false>` / `--no-web-search`: Codex web search.
  - `--header <k=v>`: Header for this client only (pass `k=` to remove).
  - `--option <k=v>`: Generic client option (pass `k=` to remove).

Target overrides are stored per provider *and* per client, so switching provider
in the same client keeps each provider's settings (a third-party gateway may
need `--fast` while the first-party endpoint does not). Only clients that
declare support for an option accept it; anything else is an error rather than a
silent no-op. Active clients using the provider are re-applied automatically.

```bash
# Create
xpx set deepseek --base-url https://api.deepseek.com/v1 --key sk-xxx

# Update provider fields
xpx set deepseek --default-model deepseek-chat
xpx set deepseek --key sk-new-key
xpx set deepseek --name ds-corp

# Update one client's overrides
xpx set deepseek codex --fast --wire-api responses
xpx set deepseek codex --header x-custom-id=123
```

---

## 3. Models and Catalog (`models`)

### `xpx models sync <provider>`
Discover remote models from `{base_url}/models` and enrich them with known context windows, token limits, and reasoning levels from the built-in catalog.

- **Options**:
  - `--force`: Force overwrite existing custom reasoning levels for all models under this provider.

```bash
xpx models sync deepseek
```

### `xpx models list [provider]`
List cached models for a provider or all providers.

- **Options**:
  - `--remote`: Query the remote endpoint directly without reading the local catalog cache.

```bash
xpx models list deepseek
```

### `xpx models set <provider> <model>`
Create or update a model entry in a provider's catalog. This is the single
create-or-update command: `models add` was removed because it upserted too, but
with a different flag set and an auto-swapping positional order that made
`add <a> <b>` ambiguous.

- **Options**:
  - `--display-name <name>`: Human-readable name shown in client pickers.
  - `--default`: Mark this model as the provider's default model.
  - `--context <int>`: Set context window size in tokens.
  - `--max-output <int>`: Set max output tokens limit.
  - `--effort <level[,level...]>`: Supported reasoning effort ladder.
  - `--modalities <m[,m]>`: Input modalities (e.g. `text,image`).
  - `--overwrite`: Replace existing metadata instead of merging into it.

```bash
xpx models set deepseek deepseek-reasoner --default --effort high
xpx models set openrouter claude-3-7-sonnet --context 200000 --modalities text,image
```

---

## 4. Client Application & Switching (`apply`)

The `apply` command is the **single point of mutation** for external agent configs.

### Syntax
```bash
xpx apply [target] [provider_spec] [options]
```

- **Positional Arguments**:
  - `target`: Target client (`codex`, `opencode`, `cursor`, `claude`, `agy`, `pi`), or comma-separated list (`codex,pi`).
  - `provider_spec`:
    - `<provider>`: Use provider with its default model.
    - `<provider>/<model>`: Use provider with a specific model.
    - `:<model>`: Keep the active provider, but switch to a different model.
- **Options**:
  - `--all`: Apply across all installed client targets.
  - `--account <name>`: Apply a saved OAuth or session account (e.g. `xpx apply agy --account work`).
  - `--model <id>`: Explicit model identifier flag.
  - `--clear`: Reset client configuration back to official defaults.
  - `--dry-run`: Preview file modifications and configuration diff without touching the disk.
  - `--no-save`: Do not persist target-specific overrides from the command line into the provider's archive.
  - **Client Overrides (applied and automatically remembered)**:
    - `--header <k=v>`: Custom HTTP headers.
    - `--fast` / `--no-fast`: Codex fast mode.
    - `--wire-api <chat|responses>`: Codex wire API.
    - `--web-search <true|false>`: Codex standalone web search.

Client overrides and protocols are validated before anything is written. Passing
`--fast` to a client that cannot honor it is an error, not a silent no-op, and a
provider whose protocol a client does not support is rejected with the list of
protocols that client accepts. With `--all`, incompatible targets are skipped
with a printed reason so one mismatch cannot abort the whole sweep.

```bash
# Apply deepseek to Codex with fast mode enabled (remembers fast mode for next time)
xpx apply codex deepseek --fast

# Apply deepseek to multiple clients at once
xpx apply codex,opencode deepseek

# Switch model only on active provider for OpenCode
xpx apply opencode :deepseek-chat

# Apply an Antigravity account
xpx apply agy --account work

# Preview changes with dry-run
xpx apply codex deepseek --dry-run

# Reset client to official defaults
xpx apply codex --clear
```

---

## 5. Account Lifecycle (`account`)

### `xpx account login <target> [name]`
Initiate the target client's native OAuth login flow (e.g., Google OAuth for Antigravity).

```bash
xpx account login agy work
```

### `xpx account snapshot <target> <name>`
Snapshot currently active session or credential files from the target client (e.g., Cursor SQLite session or Codex official `auth.json`) into a named account asset.

```bash
xpx account snapshot codex official-work
xpx account snapshot cursor personal
```

### `xpx account list`
List all saved accounts and snapshots across targets.

```bash
xpx account list
```

### `xpx account usage [target] [name]`
Query quota and remaining limits (e.g. Antigravity 5-hour and weekly quota).

```bash
xpx account usage agy work
```

---

## 6. Dashboard, Verification, and Diagnostics

### `xpx status`
Display the global dashboard showing active providers, models, and account quotas across all detected client agents.

```bash
xpx status
```

### `xpx doctor [--fix]`
Run comprehensive health checks across all detected clients:
- Verifies syntax and parseability of client configuration files.
- Checks API key format and endpoint reachability.
- Validates state consistency and cleans dangling references when `--fix` is passed.

```bash
xpx doctor
xpx doctor --fix
```

### `xpx test [provider] [--deep]`
Single entry point for connectivity testing, with two depths:

**Shallow (default)** — one HTTP GET against each provider's `/models` endpoint.
Reports status code, latency, and model count. This proves credentials and
network work, but says nothing about whether a client can actually use them.

**Deep (`--deep`)** — spawns each target client and sends a real prompt,
verifying the whole client → provider path. Slow (seconds per target) and it
consumes tokens.

Use shallow first: if it fails, the problem is network/credentials. If it passes
but `--deep` fails, the problem is on the client side (config not applied,
incompatible CLI version, session conflict).

- **Arguments**:
  - `provider`: Provider to probe. Only meaningful in shallow mode; combined
    with `--deep` it scopes the deep probe to that provider.
- **Options**:
  - `--deep`: Also run a real prompt through client CLIs.
  - `--target <clients>`: Clients for `--deep`, comma-separated. Defaults to all
    installed clients.
  - `--model <id>`: Model for `--deep` (default: the provider's default model).
  - `--prompt <text>`: Prompt for `--deep` (default: `"say hi"`).
  - `--timeout <int>`: Per-target timeout in seconds for `--deep` (default: 60s).
  - `--all`: All providers (shallow) / all clients (deep).

Provider-scoped deep probes are supported where the client can redirect a single
run without touching your configuration (`pi`, `opencode`). Clients whose
configuration is only read from disk (`codex`, `claude`, `agy`) reject a scoped
probe with an actionable message instead of silently testing the wrong provider;
`cursor` is an IDE and only supports an install check. An unknown provider name
is rejected before any CLI runs, so a typo can never report a false success.

Deep probes never pollute your history: `codex` runs with `--ephemeral`,
`claude` with `--no-session-persistence`, `pi` with `--no-session`, and
`opencode` is pointed at a throwaway database.

```bash
# Shallow: provider reachability
xpx test
xpx test deepseek
xpx test --all

# Deep: end-to-end through every installed client
xpx test --deep

# Deep, scoped to one provider / client / model
xpx test workbuddy2api --deep --target pi
xpx test workbuddy2api --deep --target pi --model cn:glm-5.3
```

---

## 7. Migration, Backups, and Self-Upgrade

### `xpx migrate [--dry-run]`
Scan local environment and migrate legacy configurations from previous 1.x CLIs (Codex `cpx`, OpenCode `opx`, Claude `clpx`, Cursor `cupx`, Antigravity `apx`) into `~/.xpx/`.

- **Options**:
  - `--dry-run`: Inspect and preview all discovered legacy providers and accounts without writing to disk.

```bash
# Preview discovered legacy configurations
xpx migrate --dry-run

# Run full migration
xpx migrate
```

### `xpx import [file]`
Smart format-sniffing import:
- **Without `file`**: Automatically executes the legacy migration scan.
- **With `file`**: Automatically detects format (Codex TOML, OpenCode JSON, Claude settings, or xpx backup) without requiring manual flags.

```bash
# Run migration scan
xpx import

# Import specific file
xpx import my-backup.json
```

### `xpx export [file]`
Export all providers, accounts, and configuration into a unified JSON backup file.

```bash
xpx export backup-2026.json
```

### `xpx upgrade`
Self-upgrade the standalone `xpx` binary to the latest release from GitHub.

- `--check`: Check if an update is available without downloading.
- `--notes`: Print latest release notes.
- `--dry-run`: Preview download and replacement steps.

```bash
xpx upgrade --check
xpx upgrade --notes
xpx upgrade
```
