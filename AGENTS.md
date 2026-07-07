# Repository Guidelines

## Project Structure & Module Organization

This repository is a small Python CLI for managing Codex provider config and auth snapshots.

- `codex_provider.py`: main implementation, command routing, file IO, and provider logic.
- `codex-provider`: shell launcher that executes the Python entrypoint.
- `README.md`: user-facing command reference and examples.
- `codex-provider-bin.spec`: PyInstaller spec for the standalone binary.
- `build/` and `dist/`: generated artifacts from packaging; treat them as outputs, not source.

Keep new code near `codex_provider.py` unless the file is being intentionally split into modules.

## Build, Test, and Development Commands

Run commands from the repository root:

- `python3 codex_provider.py --help`: inspect the CLI directly.
- `./codex-provider status`: run the wrapper script the same way end users do.
- `./.venv/bin/python -m PyInstaller --clean -y codex-provider-bin.spec`: rebuild the packaged binary into `dist/`.
- `./dist/codex-provider-bin --help`: confirm the packaged binary starts and exposes expected commands.

There is no formal test suite yet. Validate the exact commands touched by your change, especially `auth detail`, `auth edit`, `config detail`, `config edit`, `switch`, and `doctor`.

## Coding Style & Naming Conventions

Use Python 3, 4-space indentation, and ASCII by default. Match the existing style: small helper functions, explicit exceptions, and `snake_case` names for functions and variables. Keep CLI wording stable and explicit; prefer names like `auth detail` over overloaded shortcuts.

Do not edit generated files in `build/` or `dist/` by hand.

## Testing Guidelines

Favor command-level verification with isolated state. When testing commands that read or write `~/.codex` or `~/.codex-provider`, use a temporary `HOME` to avoid touching real user data. Record the validation commands in your change notes when behavior changes are non-trivial.

## Commit & Pull Request Guidelines

History is currently minimal, so use short imperative commit messages such as `Add config detail command` or `Rebuild binary after CLI changes`. Pull requests should include a concise behavior summary, the commands used for validation, and any filesystem side effects. Include terminal screenshots only when output formatting is the change being reviewed.
