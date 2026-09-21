# Command Reference (xpx 2.0.0)

This document covers `xpx` version 2.0.0, the unified AI agent provider control plane. Run `xpx <command> --help` for the exact parser surface of any command.

## Command Tree Overview

```text
xpx
├── add <name> [base_url]
├── list
├── show <name>
├── delete <name>
├── rename <old> <new>
│
├── auth
│   ├── show [name]
│   └── set <name>
│
├── config
│   ├── show [name] [target]
│   └── set <name> [target]
│
├── models
│   ├── sync <provider>
│   ├── list [provider]
│   └── set <model> <provider>
│
├── apply [target] [provider_spec]
│
├── account
│   ├── login <target> [name]
│   ├── snapshot <target> <name>
│   ├── list
│   └── usage [target] [name]
│
├── status
├── doctor
├── test [provider]
├── ping [target] [provider_spec]
├── migrate [--dry-run]
├── import [file]
├── export [file]
└── upgrade
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

### `xpx show <name>`
Inspect provider properties and any saved target-specific overrides.

```bash
xpx show deepseek
```

### `xpx delete <name>`
Delete a provider from the central store.

- **Options**:
  - `--full`: Also remove this provider's configuration from all active client targets.
  - `--dry-run`: Preview changes without deleting.

```bash
xpx delete deepseek --full
```

### `xpx rename <old> <new>`
Rename a provider asset.

```bash
xpx rename deepseek ds-corp
```

---

## 2. Credentials and Configuration (`auth` / `config`)

### `xpx auth show [name]`
Display masked API key summaries (first 4 and last 4 characters, length, and format validity).

```bash
xpx auth show deepseek
```

### `xpx auth set <name>`
Update the API key for a provider. If the provider is currently active in any client targets, `xpx` automatically updates and re-renders configuration for those targets.

- **Options**:
  - `--key <text>`: New API key.
  - `--key-stdin`: Read key from stdin.

```bash
xpx auth set deepseek --key "sk-new-key"
```

### `xpx config set <name> [target]`
Update configuration settings. Automatically handles universal base settings vs. target-specific overrides:

- **Without `target`** (universal base settings):
  - `--base-url <url>`: Update endpoint base URL.
  - `--default-model <model>`: Update default model.
  - *Re-applies to all active targets automatically.*
- **With `target`** (target-specific override settings):
  - `--header <k=v>`: Add or update a client-specific header (pass `k=` to remove).
  - `--fast` / `--no-fast`: Codex-specific fast mode.
  - `--wire-api <chat|responses>`: Codex-specific wire API.
  - `--web-search <true|false>`: Codex-specific web search toggle.
  - `--option <k=v>`: Generic client override option.

```bash
# Universal base update
xpx config set deepseek --base-url https://api.deepseek.com/v1

# Target-specific override for Codex
xpx config set deepseek codex --fast --header x-custom-id=123
```

### `xpx config show [name] [target]`
Inspect effective configuration, merging universal base values with target-specific overrides.

```bash
xpx config show deepseek codex
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

### `xpx models set <model> <provider>`
Configure model metadata or set the provider's default model.

- **Options**:
  - `--default`: Mark this model as the provider's default model.
  - `--context <int>`: Set context window size in tokens.
  - `--max-output <int>`: Set max output tokens limit.
  - `--effort <level>`: Set default reasoning effort level (e.g. `high`, `medium`, `low`).

```bash
xpx models set deepseek-reasoner deepseek --default --effort high
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
  - `--clear` / `--reset`: Reset client configuration back to official defaults.
  - `--dry-run`: Preview file modifications and configuration diff without touching the disk.
  - `--no-save`: Do not persist target-specific overrides from the command line into the provider's archive.
  - **Client Overrides (applied and automatically remembered)**:
    - `--header <k=v>`: Custom HTTP headers.
    - `--fast` / `--no-fast`: Codex fast mode.
    - `--wire-api <chat|responses>`: Codex wire API.
    - `--web-search <true|false>`: Codex standalone web search.

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
xpx apply codex --reset
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

### `xpx test [provider]`
Perform HTTP API probe tests against provider `/models` endpoints:
- Reports HTTP status code, latency (ms), and available model count.
- `--all`: Probe all configured providers.

```bash
xpx test deepseek
xpx test --all
```

### `xpx ping [target] [provider_spec]`
End-to-end integration test running a minimal prompt through the actual client binary.

- **Options**:
  - `--prompt <text>`: Custom prompt to send (default: `"say hi"`).
  - `--timeout <int>`: Timeout in seconds (default: 60s).
  - `--all`: Concurrently execute verification across all installed targets using a thread pool.

```bash
# Test single client
xpx ping codex deepseek

# Concurrently test all installed clients
xpx ping --all
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
