<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/logo-light.svg">
    <img alt="codex-provider" src=".github/logo-light.svg" width="440">
  </picture>
</div>

<div align="center">

[![License: MIT][license-shield]][license-url]
[![Release][release-shield]][release-url]
[![CI][ci-shield]][ci-url]
[![Python 3.11+][python-shield]][python-url]

</div>

<div align="center">
  <a href="README-CN.md">简体中文</a> &middot;
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#usage">Usage</a> &middot;
  <a href="docs/command-reference.md">Command Reference</a> &middot;
  <a href="https://github.com/Fel1xKan/codex-provider/issues/new?labels=bug">Report Bug</a>
</div>

> Switch Codex, OpenCode, Antigravity, and Cursor accounts and models without hand-editing credentials or global configuration.

The four CLIs are built on a shared command registry and backend adapter
framework; see [docs/architecture.md](docs/architecture.md) for the command
definition model and how to onboard a new agent provider.

---

## Why codex-provider?

AI coding CLIs store providers, models, and credentials in different formats and
locations. If you regularly move between official accounts, compatible API
providers, or Antigravity accounts, manual edits are easy to get wrong and hard
to audit. This project gives each tool a focused CLI with aligned commands,
validation, safe writes, and dry-run previews.

## Features

- **Switch without manual edits** - select saved providers or accounts while preserving unrelated global configuration.
- **Isolate the official Codex login** - snapshot it as a provider and remove managed API-provider entries when switching back.
- **Keep secrets out of terminal output** - inspect authentication metadata and redacted configuration without printing credential values.
- **Verify the entire path** - probe `/models` endpoints or run a minimal command through Codex, OpenCode, or Antigravity.
- **Manage OpenCode models** - discover remote model IDs, sync new models without deleting metadata, and choose a model while switching.
- **Manage Antigravity accounts** - log in, import account snapshots, switch accounts, and inspect 5-hour and weekly quota remaining.
- **Manage Cursor accounts and models** - snapshot signed-in Cursor accounts, swap auth rows in the Cursor SQLite database, and switch models across every Composer surface.
- **Preview and recover changes** - use dry runs, import pre-change snapshots retained by Codex provider mutations, and export or import provider data as JSON.
- **Move quickly between recent providers** - interactive pickers and list output prioritize recently used entries.

## Choose Your CLI

| CLI | Use it for | Native configuration |
|-----|------------|----------------------|
| `codex-provider` | Codex-compatible API providers, per-provider catalog and web-search options, official-login snapshots, and auth snapshots | `~/.codex` and `~/.codex-provider` |
| `opencode-provider` | OpenCode providers, credentials, default models, and model discovery | XDG OpenCode config, data, and state directories |
| `agy-provider` | Antigravity accounts, login snapshots, switching, and quota checks | `~/.gemini/antigravity-cli` and `~/.gemini/agy-provider` |
| `cursor-provider` | Cursor accounts and model selection stored in the Cursor SQLite database | `%APPDATA%\Cursor\User\globalStorage\state.vscdb` and `~/.cursor-provider` |

The Codex and OpenCode CLIs intentionally share command names and behavior for
their common operations. Codex adds `official` plus focused `config set` and
catalog options; OpenCode adds `models`; Antigravity adds `login` and `usage`;
Cursor adds `model` because those workflows are backend-specific.

## When to Use

Use these CLIs when you maintain multiple providers or accounts and want a
repeatable way to switch, validate, back up, and troubleshoot them. They are
especially useful in scripts because mutating commands expose `--dry-run` and
return non-zero status codes on failure.

This project does not create provider subscriptions, install the target Codex,
OpenCode, Antigravity, or Cursor tools, or bypass provider authentication. It
manages configuration and credentials that you already control.

## Quick Start

```bash
pipx install git+https://github.com/Fel1xKan/codex-provider.git
codex-provider status
```

Replace the second command with `opencode-provider status`,
`agy-provider status`, or `cursor-provider status` for the tool you use.

## Install

### With pipx

```bash
pipx install git+https://github.com/Fel1xKan/codex-provider.git
```

This installs all four commands in isolated Python packaging. Upgrade with:

```bash
pipx upgrade opencode-provider
```

### Standalone binaries

Linux (x86_64), Windows (x86_64), and macOS (Apple Silicon) binaries are
published with SHA-256 checksum files on the
[GitHub Releases page][release-url]. Standalone binaries do not require a local
Python installation.

## Usage

### Switch, inspect, and validate a provider

```bash
codex-provider list
codex-provider switch my-provider --dry-run
codex-provider switch my-provider
codex-provider status
codex-provider doctor
codex-provider test my-provider
```

Omit the provider from `switch` to open an interactive picker. Recent providers
appear first. `doctor` checks stored configuration and authentication, while
`test` probes the provider endpoint.

### Use backend-specific capabilities

```bash
opencode-provider models list my-provider
opencode-provider models sync my-provider --dry-run
agy-provider login work-account
agy-provider usage work-account
cursor-provider add work --from-current
cursor-provider switch work
cursor-provider provider add deepseek --from-current
cursor-provider models sync deepseek
cursor-provider models set deepseek-v4-flash
```

`models sync` replaces `provider.<id>.models` with the provider's current
model IDs, keeping metadata for IDs that still exist and dropping IDs the
provider no longer returns; use `--all` to sync every configured provider.
Anthropic-compatible providers (`npm` is `@ai-sdk/anthropic`) are queried with
Anthropic headers. Antigravity `usage` reports 5-hour and weekly quota without
switching accounts.
Cursor `switch` rewrites the auth rows in the Cursor SQLite database, and
`models set` applies one model id to every Composer surface. Cursor `provider`
commands manage custom OpenAI-compatible providers (for example DeepSeek) in
Cursor's database, and `models sync` imports the provider's remote model list as
user-added models. The [command reference](docs/command-reference.md) covers
end-to-end `ping`,
bulk checks, provider lifecycle operations, and JSON backup or restore.

## Safety

- API keys and authentication values are not printed by inspection commands.
- Configuration writes are atomic and retain existing POSIX permissions.
- OpenCode JSONC comments, trailing commas, and unrelated global values are preserved.
- Provider filters are respected, so disabled providers cannot be selected accidentally.
- Codex provider `switch`, `delete`, `rename`, `import`, and `config set` keep the ten most recent pre-change snapshots in `~/.codex-provider/backups/`.
- `switch`, `add`, `delete`, `rename`, `import`, and supported account operations provide dry-run previews.
- Cursor writes target only the auth and model rows in `state.vscdb`; chat history and workspace state are preserved.
- API keys passed as positional command arguments are rejected; use a hidden prompt or `--api-key-stdin`.

## Command Reference

The four CLIs expose aligned provider-management commands, with focused
extensions for OpenCode model discovery, Antigravity account workflows, and
Cursor account and model switching. The reference also documents file locations,
switch behavior, secret handling, and exit semantics.

→ [Read the complete command reference](docs/command-reference.md)

## Prerequisites

| Requirement | When needed |
|-------------|-------------|
| Python 3.11+ and `pipx` | Installing from source |
| Codex, OpenCode, Antigravity, or Cursor | Running that tool's native `ping` command, or switching its accounts and models |
| Network access | Provider tests, model discovery, login, and quota checks |

## Contributing

The repository includes mirrored CLI-parity tests, isolated filesystem tests,
linting, and cross-platform PyInstaller builds.

→ [Read the contributing, testing, build, and release guide](CONTRIBUTING.md)

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

---

[license-shield]: https://img.shields.io/badge/License-MIT-green.svg
[license-url]: LICENSE
[release-shield]: https://img.shields.io/github/v/release/Fel1xKan/codex-provider
[release-url]: https://github.com/Fel1xKan/codex-provider/releases
[ci-shield]: https://img.shields.io/github/actions/workflow/status/Fel1xKan/codex-provider/ci.yml?branch=master
[ci-url]: https://github.com/Fel1xKan/codex-provider/actions/workflows/ci.yml
[python-shield]: https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white
[python-url]: https://www.python.org/downloads/
