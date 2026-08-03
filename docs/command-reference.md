# Command Reference

This document covers `codex-provider`, `opencode-provider`, and `agy-provider`
version 0.5.0. Run `<command> --help` in your installed version for the exact
parser surface.

## Command Matrix

| Command | Codex | OpenCode | Antigravity | Purpose |
|---------|:-----:|:--------:|:-----------:|---------|
| `list` | Yes | Yes | Yes | List configured providers or accounts |
| `status` | Yes | Yes | Yes | Show the active provider or account |
| `auth detail` / `auth edit` | Yes | Yes | Yes | Inspect auth metadata or edit credentials |
| `config detail` / `config edit` | Yes | Yes | Yes | Inspect or edit provider configuration |
| `doctor [--fix]` | Yes | Yes | Yes | Validate configuration and authentication |
| `test [--all]` | Yes | Yes | Yes | Test provider connectivity |
| `ping` / `p` | Yes | Yes | Yes | Run a minimal command through the target CLI |
| `switch [name] [--dry-run]` | Yes | Yes | Yes | Switch the active provider or account |
| `add` | Yes | Yes | Yes | Add a provider or import an account |
| `delete [--full] [--dry-run]` | Yes | Yes | Yes | Remove configuration, optionally including auth |
| `rename [--dry-run]` | Yes | Yes | Yes | Rename a provider or account |
| `export` / `import` | Yes | Yes | Yes | Back up or restore configuration and auth |
| `models list` / `models sync` | No | Yes | No | Discover and synchronize OpenCode models |
| `login` / `usage` | No | No | Yes | Authenticate an account or inspect quota |

Codex and OpenCode share their parsers for common commands. Backend-specific
differences exist only where the target configuration format requires them.

## Provider Discovery

```bash
codex-provider list
codex-provider status
opencode-provider list
opencode-provider status
agy-provider list
agy-provider status
```

`list` and interactive provider selection order entries by recent use. Entries
that have never been used are sorted by name. Running `list` or `status`
initializes the recency file if it does not exist.

For OpenCode, only providers explicitly declared in the global config's
`provider` object are switchable. Built-in providers that exist only in
`auth.json` are not listed because OpenCode requires a concrete model ID.

## Authentication and Configuration

```bash
codex-provider auth detail my-provider
codex-provider auth edit my-provider
codex-provider config detail my-provider
codex-provider config edit my-provider

opencode-provider auth detail my-provider
opencode-provider auth edit my-provider
opencode-provider config detail my-provider
opencode-provider config edit my-provider
```

The provider argument is optional and defaults to the current provider when the
backend has one.

- `auth detail` prints field metadata without credential values.
- `auth edit` opens the backend auth file in `$VISUAL` or `$EDITOR`, then validates the result before keeping it.
- `config detail` redacts inline secrets.
- `config edit` opens and validates provider configuration. Use `auth edit` to change an API key.
- `doctor` validates config, provider models, and auth JSON. `doctor --fix` applies repairs supported by that backend.

OpenCode currently has no legacy files that require automatic repair.

## Add a Provider

```bash
codex-provider add https://api.example.com --provider example
opencode-provider add https://api.example.com --provider example
```

By default, the command reads the API key from a hidden terminal prompt. For
scripts, pipe the value to standard input:

```bash
printf '%s\n' "$PROVIDER_API_KEY" | \
  opencode-provider add https://api.example.com \
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
| `--api-key-stdin` | Read the API key from standard input |
| `--dry-run` | Preview changes without writing files |

OpenCode accepts `--supports-websockets` for CLI compatibility but does not
store it because OpenCode has no equivalent provider field.

## Switch a Provider or Account

```bash
codex-provider switch my-provider
codex-provider switch my-provider --dry-run

opencode-provider switch my-provider
opencode-provider switch my-provider --model my-model
opencode-provider switch my-provider --model my-provider/my-model --dry-run

agy-provider switch work-account
agy-provider switch work-account --dry-run
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
codex-provider test
codex-provider test --all
codex-provider test my-provider
codex-provider ping my-provider --model gpt-5

opencode-provider test
opencode-provider test --all
opencode-provider ping my-provider --model my-model

agy-provider test
agy-provider ping work-account
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
opencode-provider models list my-provider
opencode-provider models sync my-provider
opencode-provider models sync my-provider --dry-run
opencode-provider models sync --all
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
codex-provider delete my-provider --dry-run
codex-provider delete my-provider
codex-provider delete my-provider --full
codex-provider rename my-provider new-provider --dry-run

opencode-provider delete my-provider --full
opencode-provider rename my-provider new-provider
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
codex-provider export backup.json
codex-provider export -
opencode-provider import backup.json --dry-run
opencode-provider import backup.json
```

Omit the file or use `-` to write an export to standard output or read an import
from standard input. `import --dry-run` validates and previews changes without
writing files. Exported data can contain credentials and must be protected as a
secret.

## Antigravity Accounts

### Login and import

```bash
agy-provider login work-account
agy-provider login work-account --dry-run
agy-provider add work-account --from-current
agy-provider add work-account --from-dir /path/to/account
agy-provider add work-account --login
```

`login` starts an interactive AGY login and saves the resulting account
snapshot. `add` can import the active token, import an account directory, or
delegate to the login flow.

### Quota usage

```bash
agy-provider usage
agy-provider usage work-account
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
~/.codex-provider/recent.json
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
