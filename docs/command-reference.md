# Command Reference

This document covers `codex-provider`, `opencode-provider`, `agy-provider`,
`cursor-provider`, and `claude-provider` version 1.0.0. Run `<command> --help`
in your installed version for the exact parser surface.

## Command Matrix

| Command | Codex | OpenCode | Antigravity | Cursor | Claude | Purpose |
|---------|:-----:|:--------:|:-----------:|:------:|:------:|---------|
| `list` | Yes | Yes | Yes | Yes | Yes | List configured providers or accounts |
| `status` | Yes | Yes | Yes | Yes | Yes | Show the active provider or account |
| `auth show` / `auth edit` | Yes | Yes | Yes | Yes | Yes | Inspect auth metadata or edit credentials |
| `config show` / `config edit` | Yes | Yes | Yes | Yes | Yes | Inspect or edit provider configuration |
| `doctor [--fix]` | Yes | Yes | Yes | Yes | Yes | Validate configuration and authentication |
| `test [--all]` | Yes | Yes | Yes | Yes | Yes | Test provider connectivity |
| `ping` / `p` | Yes | Yes | Yes | Yes | Yes | Run a minimal command through the target CLI |
| `switch [name] [--dry-run]` | Yes | Yes | Yes | Yes | Yes | Switch the active provider or account |
| `add` | Yes | Yes | Yes | Yes | Yes | Add a provider or import an account |
| `delete [--full] [--dry-run]` | Yes | Yes | Yes | Yes | Yes | Remove configuration, optionally including auth |
| `rename [--dry-run]` | Yes | Yes | Yes | Yes | Yes | Rename a provider or account |
| `export` / `import` | Yes | Yes | Yes | Yes | Yes | Back up or restore configuration and auth |
| `upgrade [--check] [--dry-run]` | Yes | Yes | Yes | Yes | Yes | Update the binary from the latest GitHub release |
| `models list` / `models sync` | No | Yes | No | No | Yes | Discover and synchronize OpenCode/Claude models |
| `models list` / `models set` | No | No | No | Yes | No | List or switch the Cursor model selection |
| `models sync` | No | No | No | Yes | No | Import models from a custom Cursor provider |
| `official add` | Yes | No | No | No | No | Save the current Codex login as a switchable official provider |
| `provider add` / `switch` / `delete` | No | No | No | Yes | No | Manage custom OpenAI-compatible Cursor providers |
| `login` / `usage` | No | No | Yes | No | No | Authenticate an account or inspect quota |

Codex, OpenCode, and Claude share their parsers for common commands. Backend-specific
differences exist only where the target configuration format requires them.

## Official Codex Login

```bash
codex login
cpx official add
cpx switch official
```

`official add` snapshots the current `~/.codex/auth.json` into the provider
store and records a provider with `mode = "official"`. Switching to that
provider restores the official auth snapshot and renders the runtime config
with Codex's built-in `openai` provider. cpx also removes its own
managed runtime provider block, standalone web-search override, and model
catalog pointer in that mode. Use `cpx ping official` to verify the
login; HTTP `/models` tests do not apply.

`--provider NAME` selects a different provider identifier and `--name` sets the
display name. Both `official add` and `switch` support `--dry-run` previews.

## Provider Discovery

```bash
cpx list
cpx status
opx list
opx status
apx list
apx status
clpx list
clpx status
```

`list` and interactive provider selection order entries by recent use. Entries
that have never been used are sorted by name. Running `list` or `status`
initializes the recency file if it does not exist.

For OpenCode, only providers explicitly declared in the global config's
`provider` object are switchable. Built-in providers that exist only in
`auth.json` are not listed because OpenCode requires a concrete model ID.

## Claude Providers

```bash
clpx add https://api.claude.ai --provider claudeai --model claude-sonnet-4-5
clpx switch claudeai
clpx status
```

`claude-provider` keeps its registry in `~/.claude-provider/config.json` and
auth snapshots in `~/.claude-provider/auth/<provider>.json`. Switching writes
`ANTHROPIC_BASE_URL`, the provider credential (`ANTHROPIC_AUTH_TOKEN` or
`ANTHROPIC_API_KEY`), and any provider-specific model env keys
(`ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_*_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`)
into the `env` object of `~/.claude/settings.json`. A provider can also carry a
`modelOverrides` block; switching restores it and removes it when the target
provider has none, mirroring how `codex-provider` points Codex at a per-provider
model catalog. The active provider is recorded in
`~/.claude-provider/config.json`, so Claude Code picks up the selected endpoint
and credentials on its next run. Other settings such as `permissions` and
`model` are preserved. The optional `--model` on `add` is stored per provider
as metadata; use `config set --model` to change it later.

`clpx add --from-settings` snapshots the current `env` and
`modelOverrides` from `~/.claude/settings.json` into a new provider without
prompting for a credential, which is convenient when switching between a local
gateway (for example `http://127.0.0.1:4000` with `ANTHROPIC_API_KEY`) and an
official endpoint (for example `https://api.deepseek.com/anthropic` with
`ANTHROPIC_AUTH_TOKEN`).

`clpx test` probes the Anthropic-compatible models endpoint with
`x-api-key` authentication and the standard `anthropic-version` header.
Some providers expose model discovery on a different path (DeepSeek uses
`https://api.deepseek.com/models`); set it per provider with
`clpx config set <provider> --models-url <url>`.
`clpx ping` runs a minimal `claude -p "<prompt>"` command through
the locally installed Claude Code binary so the full settings path is
exercised.

### Claude model management

```bash
clpx models sync cistern
clpx models sync --all
clpx models list cistern
clpx models list cistern --remote
clpx models set claude-sonnet-5 cistern
```

`models sync` fetches the model IDs exposed by a provider and stores them at
`~/.claude-provider/models/<provider>.json`. `models list` shows the cached
list, or fetches live with `--remote`. `models set <model> [provider]` updates
the provider's model env keys (`ANTHROPIC_MODEL`,
`ANTHROPIC_DEFAULT_*_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`) and re-renders
`~/.claude/settings.json` so the new default model applies immediately without
changing the active provider or endpoint.

## Authentication and Configuration

```bash
cpx auth show my-provider
cpx auth edit my-provider
cpx config show my-provider
cpx config edit my-provider
cpx config set my-provider \
  --supports-standalone-web-search true \
  --provider-model-catalog-json ~/.codex-provider/catalogs/custom.json
cpx config set my-provider --fast
cpx config set my-provider --fast --apply
cpx config set my-provider --no-fast
cpx config set my-provider --provider-model-catalog-json ""
cpx config set my-provider --name "New Name" \
  --wire-api chat --supports-websockets true
cpx config set my-provider \
  --header x-openai-actor-authorization=local-image-extension
cpx config set my-provider --reset
cpx config set my-provider --supports-standalone-web-search false \
  --dry-run

opx auth show my-provider
opx auth edit my-provider
opx config show my-provider
opx config edit my-provider
```

The provider argument is optional and defaults to the current provider when the
backend has one.

- `auth show` prints field metadata without credential values.
- `auth edit` opens the backend auth file in `$VISUAL` or `$EDITOR`, then validates the result before keeping it.
- `config show` redacts inline secrets.
- `config edit` opens and validates provider configuration. Use `auth edit` to change an API key.
- `config set` (Codex only) updates provider fields without opening an editor:
  `--name`, `--wire-api`, `--supports-websockets`,
  `--supports-standalone-web-search`, `--provider-model-catalog-json`,
  `--header`, and `--fast`/`--no-fast`. At least one option is required. An empty
  `--provider-model-catalog-json` clears the catalog field; a non-empty value
  is stored exactly as provided so a catalog file can be generated before the
  next switch. `--fast` enables fast mode by writing Codex's native top-level
  `service_tier = "priority"` into the runtime config; `--no-fast` clears it
  and lets Codex choose. `--reset` clears fast mode, web search, and model
  catalog options in one step.

  `--header KEY=VALUE` adds a provider HTTP header and may be repeated. It is
  written into the provider block as `http_headers = { ... }`, so Codex sends
  the header on every request to that provider. Pass `--header KEY=` (empty
  value) to remove a single header. Header values are redacted by
  `config show`.

  `config set` writes the intended provider state in the tool config. The
  runtime `~/.codex/config.toml` is generated from it by `switch`. Pass
  `--apply` to re-render the runtime config immediately for the active
  provider; otherwise run `cpx switch <provider>`.
- `doctor` validates config, provider models, and auth JSON. `doctor --fix` applies repairs supported by that backend.

OpenCode currently has no legacy files that require automatic repair.

## Add a Provider

```bash
cpx add https://api.example.com --provider example
opx add https://api.example.com --provider example
```

By default, the command reads the API key from a hidden terminal prompt. For
scripts, pipe the value to standard input:

```bash
printf '%s\n' "$PROVIDER_API_KEY" | \
  opx add https://api.example.com \
  --provider example \
  --api-key-stdin
```

API keys passed as positional arguments are rejected. Both provider CLIs accept
the following options:

| Option | Meaning |
|--------|---------|
| `--provider NAME` | Provider identifier; defaults to the base URL domain |
| `--name NAME` | Display name stored in provider configuration |
| `--wire-api API` | Wire API value; defaults to `responses` |
| `--supports-websockets true\|false` | Set WebSocket support when the backend supports it |
| `--supports-standalone-web-search true\|false` | Enable Codex standalone (live) web search by writing `web_search = "live"` into the runtime config |
| `--provider-model-catalog-json PATH` | Codex only; store a per-provider model catalog pointer. Empty clears the field |
| `--fast` / `--no-fast` | Codex only; enable or disable fast mode. `--fast` writes `service_tier = "priority"` on switch |
| `--header KEY=VALUE` | Codex only; add a provider HTTP header. Repeat to add more; `KEY=` removes one |
| `--apply` | Codex only; after `add`, switch to the new provider immediately |
| `--api-key-stdin` | Read the API key from standard input |
| `--dry-run` | Preview changes without writing files |

OpenCode accepts `--supports-websockets` for CLI compatibility but does not
store it because OpenCode has no equivalent provider field. The same applies to
`--supports-standalone-web-search`: OpenCode accepts it for parser parity but
does not persist a standalone web search flag.

## Switch a Provider or Account

```bash
cpx switch my-provider
cpx switch my-provider --dry-run

opx switch my-provider
opx switch my-provider --model my-model
opx switch my-provider --model my-provider/my-model --dry-run

apx switch work-account
apx switch work-account --dry-run
```

Running `switch` without a name opens the interactive picker. In a
non-interactive environment, provide the name explicitly.

OpenCode writes the selected value to the global config's top-level `model`
field as `provider/model`:

- If the target provider has one model, it is selected automatically.
- If the current model ID exists on the target, that ID is retained.
- Otherwise an interactive terminal opens a model menu.
- In non-interactive use, pass `--model`.

Project-level `opencode.json` files have higher precedence than global config.
A project-level top-level `model` continues to override a global switch.

## Test and Ping

```bash
cpx test
cpx test --all
cpx test my-provider
cpx ping my-provider --model gpt-5

opx test
opx test --all
opx ping my-provider --model my-model

apx test
apx ping work-account
```

`test` probes the configured provider endpoint. It accepts the current provider,
a named provider, or a direct base URL. A direct URL requires an API key from a
hidden prompt or `--api-key-stdin`; credentials in positional arguments are
rejected.

`ping` invokes the target CLI with a minimal prompt. It supports:

| Option | Default | Meaning |
|--------|---------|---------|
| `--all` | Off | Check every configured provider and print a summary |
| `--timeout SECONDS` | `120` | Target CLI timeout |
| `-m`, `--model MODEL` | Target default | Override the model for this check |
| `--prompt TEXT` | `say hi` | Prompt sent by the target CLI |

`--all` continues after individual failures and returns status 1 if any check
fails.

## OpenCode Models

```bash
opx models list my-provider
opx models sync my-provider
opx models sync my-provider --dry-run
opx models sync --all
```

`models list` fetches IDs from the OpenAI-compatible
`options.baseURL/models` endpoint without changing config. `models sync` adds
new IDs to `provider.<id>.models`, retains existing model metadata, and never
removes models.

Credentials are read from `options.apiKey` or OpenCode's auth store. API keys
are never printed. With `--all`, synchronization continues through every
provider and returns status 1 if any provider cannot be queried.

## Delete and Rename

```bash
cpx delete my-provider --dry-run
cpx delete my-provider
cpx delete my-provider --full
cpx rename my-provider new-provider --dry-run

opx delete my-provider --full
opx rename my-provider new-provider
```

`delete` removes provider configuration but retains authentication by default.
Pass `--full` to remove auth too. If a provider was already deleted, run
`delete <provider> --full` again to remove orphaned auth. Re-adding the provider
replaces retained auth with the newly entered key.

The current provider cannot be deleted until another provider is selected.
OpenCode preserves unrelated JSONC content during deletion. OpenCode rename
updates the provider key, matching auth entry, and top-level default model in
one operation.

## Export and Import

```bash
cpx export backup.json
cpx export -
opx import backup.json --dry-run
opx import backup.json
```

Omit the file or use `-` to write an export to standard output or read an import
from standard input. `import --dry-run` validates and previews changes without
writing files. Exported data can contain credentials and must be protected as a
secret.

## Automatic Snapshots

Codex provider `switch`, `delete`, `rename`, and `import` write a full
pre-change snapshot to `~/.codex-provider/backups/` before modifying provider
state. Snapshots use the export JSON format, include auth data, and are stored
with owner-only permissions. The ten most recent snapshots are retained.

Restore a snapshot with the standard import command:

```bash
cpx import ~/.codex-provider/backups/<snapshot-token>.json
```

Snapshot files contain credentials. Copy them only over trusted channels and
remove copies when they are no longer needed.

## Upgrade

```bash
cpx upgrade --check
cpx upgrade --dry-run
cpx upgrade
```

`upgrade` fetches the latest GitHub release for the current platform, verifies
the asset against its published SHA-256 checksum, and atomically replaces the
executable. `--check` only reports whether a newer version exists; `--dry-run`
prints what would be downloaded without replacing anything. The command is
available in every provider CLI and targets that CLI's own release asset.

Standalone binaries are published per platform as
`<tool>-<version>-<platform>`. Source installations managed with pip should use
`pipx upgrade <tool>` instead.

## Cursor Accounts and Models

Cursor stores the signed-in account and the model selection in its SQLite
`state.vscdb` database, so switching only rewrites a few rows.

```bash
cupx add work --from-current
cupx add work --from-current --dry-run
cupx list
cupx status
cupx switch work
cupx switch work --dry-run
cupx models list
cupx models set claude-sonnet-4-6
cupx models set claude-sonnet-4-6 --dry-run
```
`add --from-current` snapshots the account currently signed in to Cursor.
`switch` writes the saved `cursorAuth/*` tokens and the reactive account fields
into `state.vscdb`; chat history and workspace state are shared and never
touched. `delete --full` also clears the auth rows in Cursor, logging the app
out.

`models list` prints the model catalog cached in the Cursor database plus the
current selection per surface. `models set` validates the id against the catalog
and applies it to every surface (`composer`, `cmd-k`, `background-composer`,
`composer-ensemble`, `plan-execution`, `spec`, `deep-search`, `quick-agent`) and
updates `modelLastUsedAt`.

### Custom providers and model sync

Cursor supports custom OpenAI-compatible providers (for example DeepSeek)
through Settings > Models. The base URL is stored as `openAIBaseUrl` in the
Cursor database and the API key in the encrypted `secret://cursorAuth/openAIKey`
row. `cursor-provider` can capture and restore both.

```bash
cupx provider add deepseek --from-current
cupx provider add moon --base-url https://api.moon.com --api-key-stdin
cupx provider list
cupx provider switch deepseek --dry-run
cupx provider switch deepseek
cupx provider delete deepseek --full
cupx models sync deepseek
cupx models sync deepseek --dry-run
```

- `provider add --from-current` snapshots the provider currently configured in
  Cursor (base URL plus the API key row).
- `provider add --base-url` stores a new base URL and prompts for the API key
  with a hidden prompt; pass `--api-key-stdin` to pipe it in instead (identical
  behavior to `cpx add`). On Windows the key is re-encrypted into
  Cursor's secret format using the DPAPI-wrapped key in `Local State`; on macOS
  and Linux the tool reads Cursor's encryption key from the login Keychain or
  Secret Service keyring (the first terminal run asks for Keychain access). If
  the platform key cannot be read, keys can still be captured from Cursor with
  `--from-current`.
- `provider switch` rewrites `openAIBaseUrl` and the secret row, then `models
  sync` fetches `GET {base_url}/models` and adds missing ids to the Cursor
  model catalog as user-added entries (existing entries are preserved; models
  are never removed).
- `list` prints three sections: saved accounts, custom providers (with the
  active provider marked), and user-added models with their provider origin.
- `provider delete --full` clears the base URL and key row in Cursor.

Custom API keys only affect chat models; Tab completion continues to use
Cursor's built-in models.

Cursor keeps the database and its in-memory state in sync while running; quit
Cursor before `switch`, `models set`, `provider switch`, or `delete --full` so
the change is not overwritten. These commands warn when a Cursor process is
detected.

`test` and `ping` validate the saved access token locally: the JWT is decoded,
its expiry is checked, and the account identity is printed. They return status 1
for an expired token.

## Antigravity Accounts

### Login and import

```bash
apx login work-account
apx login work-account --dry-run
apx add work-account --from-current
apx add work-account --from-dir /path/to/account
apx add work-account --login
```

`login` starts an interactive AGY login and saves the resulting account
snapshot. `add` can import the active token, import an account directory, or
delegate to the login flow.

### Quota usage

```bash
apx usage
apx usage work-account
```

Without an account name, `usage` queries the current account. It initializes
Code Assist for that account, uses the returned project for the quota request,
and reports remaining 5-hour and weekly limits by model group. Expired access
tokens are refreshed in memory; the active account and saved credentials are
not modified.

## Storage Locations

### Codex

```text
~/.codex/
~/.codex-provider/config.toml
~/.codex-provider/auth/
~/.codex-provider/backups/
~/.codex-provider/recent.json
~/.codex-provider/.lock
```

### OpenCode

The first existing global config path in this order is used:

```text
~/.config/opencode/opencode.jsonc
~/.config/opencode/opencode.json
~/.config/opencode/config.json
```

Authentication and provider recency are stored at:

```text
~/.local/share/opencode/auth.json
~/.local/state/opencode/opencode-provider-recent.json
```

`XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and `XDG_STATE_HOME` are respected on macOS
and Linux.

### Antigravity

```text
~/.gemini/antigravity-cli/
~/.gemini/config/config.json
~/.gemini/agy-provider/auth.json
~/.gemini/agy-provider/state/
```

### Cursor

```text
~/.cursor-provider/auth.json
~/.cursor-provider/state/state.json
~/.cursor-provider/state/recent.json
```

The Cursor database written by this CLI is:

```text
%APPDATA%\Cursor\User\globalStorage\state.vscdb   (Windows)
~/Library/Application Support/Cursor/User/globalStorage/state.vscdb   (macOS)
~/.config/Cursor/User/globalStorage/state.vscdb   (Linux)
```

### Claude

```text
~/.claude/settings.json
~/.claude-provider/config.json
~/.claude-provider/auth/
~/.claude-provider/recent.json
~/.claude-provider/.lock
```

`~/.claude/settings.json` is the Claude Code global settings file managed by
Claude itself; this CLI only adds or updates the `env` keys
`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`. The settings path can be
customized with the `settings_path` field in `~/.claude-provider/config.json`.

## Safety and Exit Semantics

- Credential values are redacted from inspection output.
- Writes are atomic and preserve existing POSIX file modes.
- Provider state directories and secret files use restrictive permissions.
- OpenCode JSONC comments and trailing commas are preserved.
- Unrelated global configuration remains unchanged.
- Disabled or excluded providers cannot be selected accidentally.
- A successful command returns status 0; validation, connectivity, and command failures return a non-zero status.
- `--all` operations continue after individual failures and summarize the final result.

Return to the [README](../README.md) or [Chinese README](../README-CN.md).
