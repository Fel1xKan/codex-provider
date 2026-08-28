# Repository Guidelines

## Project Structure & Module Organization

This repository contains five Python CLIs for managing Codex, OpenCode, Antigravity, Cursor, and Claude provider configuration and authentication.

- `src/cli/`: CLI entrypoints (`codex_provider.py`, `opencode_provider.py`, `agy_provider.py`, `cursor_provider.py`, `claude_provider.py`).
- `src/lib/`: modularized packages (`common/`, `codex/`, `opencode/`, `agy/`, `cursor/`, `claude/`).
- `cpx`, `opx`, `apx`, `cupx`, `clpx`: shell launchers for the Python entrypoints.
- `codex-provider-bin.spec`, `opencode-provider.spec`, `agy-provider.spec`, `cursor-provider.spec`, `claude-provider.spec`: PyInstaller specs for the standalone binaries.
- `build/` and `dist/`: generated artifacts from packaging; treat them as outputs, not source.

Keep backend-specific code near its provider module under `src/lib/`. Put genuinely shared behavior in `src/lib/common/`.

## Dual CLI API Consistency

`cpx` and `opx` must expose a consistent API for every shared command. A change to a shared command must update both CLIs in the same change, even when the request mentions only one of them.

- Keep shared command names, aliases, positional arguments, options, defaults, validation rules, exit-code semantics, dry-run behavior, and user-facing result wording aligned.
- Before completing a change to `list`, `status`, `auth`, `config`, `doctor`, `switch`, `test`, `ping`, `add`, `delete`, or `rename`, inspect and update the corresponding parser, dispatch path, implementation, documentation, and tests for both CLIs.
- Put shared parsing and dispatch behavior in `codex_provider_lib` when practical. Keep backend-specific config, auth, model selection, and filesystem logic in the relevant provider module.
- Backend-specific differences are allowed only when the target tools genuinely require them. Document the difference and keep the remaining command shape consistent. OpenCode-only `models` commands are an explicit example.
- Add mirrored behavioral tests for both CLIs and retain the parser command-matrix test so API drift fails during validation.
- Do not mark a shared CLI change complete after validating only one executable.

## Build, Test, and Development Commands

Run commands from the repository root:

- `./cpx --help` and `./opx --help`: inspect both wrapper CLIs.
- `./cpx status` and `./opx status`: run the wrappers the same way end users do.
- `./.venv/bin/python -m pytest -q`: run the complete test suite, including CLI parity checks.
- `./.venv/bin/ruff check .`: run static checks.
- `./.venv/bin/python build.py --target codex` and `./.venv/bin/python build.py --target opencode`: rebuild both standalone binaries into `dist/`.
- `./dist/cpx --help` and `./dist/opx --help`: confirm both packaged binaries start and expose the expected commands.

In addition to the full suite, validate the exact commands touched by your change, especially `auth show`, `auth edit`, `config show`, `config edit`, `switch`, and `doctor` in both CLIs.

## Coding Style & Naming Conventions

Use Python 3, 4-space indentation, and ASCII by default. Match the existing style: small helper functions, explicit exceptions, and `snake_case` names for functions and variables. Keep CLI wording stable and explicit; prefer names like `auth show` over overloaded shortcuts.

Do not edit generated files in `build/` or `dist/` by hand.

## Testing Guidelines

Favor command-level verification with isolated state. When testing commands that read or write `~/.codex` or `~/.codex-provider`, use a temporary `HOME` to avoid touching real user data. Record the validation commands in your change notes when behavior changes are non-trivial.

## Commit & Pull Request Guidelines

History is currently minimal, so use short imperative commit messages such as `Add config show command` or `Rebuild binary after CLI changes`. Pull requests should include a concise behavior summary, the commands used for validation, and any filesystem side effects. Include terminal screenshots only when output formatting is the change being reviewed.
