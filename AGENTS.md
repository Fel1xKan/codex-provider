# Repository Guidelines

## Project Structure & Module Organization

This repository contains the unified `xpx` control plane CLI for managing Codex, OpenCode, Cursor, Claude, Antigravity, and Pi provider configuration and authentication.

- `src/cli/`: CLI entrypoint (`xpx.py`).
- `src/lib/`: modularized packages:
  - `common/`: shared utilities, OS cryptography, self-upgrade, and constants.
  - `xpx/`: unified control plane core:
    - `store/`: persistence models and directory managers for `~/.xpx/`.
    - `adapters/`: target client adapters (`codex`, `opencode`, `cursor`, `claude`, `agy`, `pi`).
    - `models/`: model discovery, catalog enrichment, and reasoning settings.
    - `commands/`: CLI command domains (`apply`, `provider`, `auth`, `config`, `account`, etc.).
    - `accounts/`: session and OAuth account handlers.
- `xpx`: shell launcher.
- `xpx.spec`: PyInstaller spec for the standalone `xpx` binary.
- `build/` and `dist/`: generated artifacts from packaging; treat them as outputs, not source.

## Single Control Plane Architecture

All configuration state is centrally managed in `~/.xpx/`. Native client modifications are isolated strictly to the `apply` command domain.

- The primary CLI binary is `xpx`.
- New capabilities should be added directly to the appropriate `xpx` command domain or target adapter.

## Build, Test, and Development Commands

Run commands from the repository root:

- `./xpx --help`: inspect the unified control plane CLI.
- `./xpx status`: run the multi-client dashboard.
- `./.venv/bin/python -m pytest -q`: run the complete test suite.
- `./.venv/bin/ruff check .`: run static checks.
- `./.venv/bin/python build.py`: build the standalone `xpx` binary into `dist/`.
- `./dist/xpx --help` and `./dist/xpx status`: confirm the packaged binary starts and works.

In addition to the full suite, validate the exact commands touched by your change, especially `auth show`, `auth set`, `config show`, `config set`, `apply`, `status`, and `doctor`.

## Coding Style & Naming Conventions

Use Python 3, 4-space indentation, and ASCII by default. Match the existing style: small helper functions, explicit exceptions, and `snake_case` names for functions and variables. Keep CLI wording stable and explicit; prefer names like `auth show` over overloaded shortcuts.

Do not edit generated files in `build/` or `dist/` by hand.

## Testing Guidelines

Favor command-level verification with isolated state. When testing commands that read or write `~/.codex` or `~/.codex-provider`, use a temporary `HOME` to avoid touching real user data. Record the validation commands in your change notes when behavior changes are non-trivial.

## Commit & Pull Request Guidelines

History is currently minimal, so use short imperative commit messages such as `Add config show command` or `Rebuild binary after CLI changes`. Pull requests should include a concise behavior summary, the commands used for validation, and any filesystem side effects. Include terminal screenshots only when output formatting is the change being reviewed.
