<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset=".github/logo-light.svg">
    <img alt="xpx" src=".github/logo-light.svg" width="440">
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
  <a href="#features">Features</a> &middot;
  <a href="#usage">Usage</a> &middot;
  <a href="docs/command-reference.md">Command Reference</a> &middot;
  <a href="docs/architecture.md">Architecture</a> &middot;
  <a href="https://github.com/Fel1xKan/codex-provider/issues/new?labels=bug">Report Bug</a>
</div>

> Unified AI Agent Provider Control Plane for Codex, OpenCode, Claude, Cursor, Antigravity, and Pi.

---

## Why xpx?

Modern AI coding agents (Codex, OpenCode, Claude Code, Cursor, Antigravity, Pi) each store providers, credentials, and model configurations in isolated locations and inconsistent formats (TOML, JSON, SQLite, environment files). Managing multiple providers, official logins, or API keys across several tools requires constant manual edits, risking formatting bugs and secret exposure.

**`xpx` centralizes all AI agent configuration into a single control plane.** Manage your providers and accounts once in `~/.xpx/`, and let `xpx apply` render configurations into any agent with automatic memory and zero side effects until applied.

---

## Supported Agents

| Target Agent | Configuration Target | Capabilities Supported |
|--------------|----------------------|------------------------|
| **Codex** | `~/.codex/config.toml` | Custom providers, fast mode, wire API, web search, reasoning levels |
| **OpenCode** | `opencode.json` (XDG config) | Provider discovery, models catalog, JSONC formatting preservation |
| **Claude Code** | `~/.claude/settings.json` | Custom Anthropic-compatible endpoints, default models |
| **Cursor** | `state.vscdb` (SQLite) | Custom OpenAI-compatible providers, model switching, account snapshots |
| **Antigravity** | `~/.gemini/antigravity-cli` | OAuth accounts, session switching, 5-hour and weekly quota tracking |
| **Pi Agent** | `~/.pi/agent/models.json` / `config.yaml` | Multi-model definitions, custom providers |

---

## Features

- **Single Point of Mutation**: Provider additions (`xpx add`), credential updates (`xpx auth set`), and configuration edits (`xpx config set`) only modify `~/.xpx/`. External agent configs are touched exclusively during `xpx apply`.
- **Automatic Override Memory**: Apply client-specific flags once (e.g. `xpx apply codex deepseek --fast`), and `xpx` remembers them automatically for future applies.
- **Unified Multi-Client Dashboard**: Run `xpx status` to see the active provider, model, and quota across all installed agents in a single view.
- **Concurrent Integration Testing**: Run `xpx ping --all` to concurrently verify end-to-end prompt latency across all installed coding agents.
- **Centralized Model Catalog**: Auto-sync model limits, token windows, and reasoning tiers from upstream vendor documentation (`xpx models sync`).
- **Full Account Lifecycle**: Manage OAuth logins and session snapshots (`xpx account login`, `xpx account snapshot`, `xpx account usage`).
- **Comprehensive Diagnostics**: Run `xpx doctor [--fix]` to validate configuration syntax, test API reachability, and repair dangling references.
- **Zero Python Dependency**: Distributed as a single self-contained standalone binary with built-in self-upgrade (`xpx upgrade`).

---

## Quick Start

### Install Standalone Binary (Recommended)

Linux / macOS:
```bash
curl -LsSf https://raw.githubusercontent.com/Fel1xKan/codex-provider/master/scripts/install.sh | sh
```

Windows (PowerShell):
```powershell
irm https://raw.githubusercontent.com/Fel1xKan/codex-provider/master/scripts/install.ps1 | iex
```

### Install with pipx

```bash
pipx install git+https://github.com/Fel1xKan/codex-provider.git
```

---

## Usage

### 1. Add and Manage Providers

```bash
# Add a provider with interactive key entry
xpx add deepseek https://api.deepseek.com/v1 --default-model deepseek-reasoner

# Or pipe in an API key via stdin
echo "sk-secret" | xpx add openrouter https://openrouter.ai/api/v1 --key-stdin

# List all configured providers
xpx list

# Update an API key (automatically re-applies to all active agents)
xpx auth set deepseek --key "sk-new-key"
```

### 2. Apply to Target Agents

```bash
# Apply to Codex with fast mode enabled (remembers fast mode for next time)
xpx apply codex deepseek --fast

# Apply to multiple targets simultaneously
xpx apply codex,opencode deepseek

# Apply to all detected agents
xpx apply --all deepseek

# Switch model only on the active provider
xpx apply opencode :deepseek-chat

# Preview changes without touching files
xpx apply codex deepseek --dry-run

# Reset a client to official defaults
xpx apply codex --reset
```

### 3. Synchronize Models & Reasoning Tiers

```bash
# Fetch provider models and enrich with context windows and reasoning tiers
xpx models sync deepseek

# List synced models
xpx models list deepseek

# Set default model and default reasoning effort
xpx models set deepseek-reasoner deepseek --default --effort high
```

### 4. Account Lifecycle & Quotas

```bash
# Log in via OAuth (e.g. Google OAuth for Antigravity)
xpx account login agy work

# Inspect 5-hour and weekly quota
xpx account usage agy work

# Snapshot current official session from Codex or Cursor
xpx account snapshot codex official-work
xpx account snapshot cursor personal
```

### 5. Diagnostics and Health Checks

```bash
# View dashboard across all clients
xpx status

# Run system health check and repair dangling state
xpx doctor --fix

# Probe HTTP API endpoints
xpx test --all

# Concurrent end-to-end prompt test across all installed clients
xpx ping --all
```

### 6. Migration and Backups

```bash
# Preview legacy configurations across cpx, opx, apx, cupx, clpx
xpx migrate --dry-run

# Migrate all legacy tools' configurations into ~/.xpx/
xpx migrate

# Import from a specific config file or backup JSON
xpx import backup.json

# Export central state to JSON backup
xpx export backup.json

# Self-upgrade to latest release
xpx upgrade
```

---

## Documentation

- [Command Reference](docs/command-reference.md): Detailed argument definitions, option flags, and syntax for every command.
- [Architecture & Extension Guide](docs/architecture.md): Internal design principles, data flow topology, and how to write a new `TargetAdapter`.
- [Contributing Guidelines](CONTRIBUTING.md): Local development, testing, and packaging instructions.

---

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

[license-shield]: https://img.shields.io/badge/License-MIT-green.svg
[license-url]: LICENSE
[release-shield]: https://img.shields.io/github/v/release/Fel1xKan/codex-provider
[release-url]: https://github.com/Fel1xKan/codex-provider/releases
[ci-shield]: https://img.shields.io/github/actions/workflow/status/Fel1xKan/codex-provider/ci.yml?branch=master
[ci-url]: https://github.com/Fel1xKan/codex-provider/actions/workflows/ci.yml
[python-shield]: https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white
[python-url]: https://www.python.org/downloads/
