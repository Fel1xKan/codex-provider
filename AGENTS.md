# Repository Guidelines

## Project Structure & Module Organization

This repository contains two Python CLIs for managing Codex and OpenCode provider configuration and authentication.

- `codex_provider.py`: Codex implementation, command routing, file IO, and provider logic.
- `opencode_provider.py`: OpenCode implementation, command routing, file IO, and provider logic.
- `codex_provider_lib/`: shared CLI parsing, validation, networking, and platform helpers.
- `codex-provider` and `opencode-provider`: shell launchers for the Python entrypoints.
- `README.md`: user-facing command reference and examples.
- `codex-provider-bin.spec` and `opencode-provider.spec`: PyInstaller specs for the standalone binaries.
- `build/` and `dist/`: generated artifacts from packaging; treat them as outputs, not source.

Keep backend-specific code near its provider module. Put genuinely shared behavior in `codex_provider_lib/`.

## Dual CLI API Consistency

`codex-provider` and `opencode-provider` must expose a consistent API for every shared command. A change to a shared command must update both CLIs in the same change, even when the request mentions only one of them.

- Keep shared command names, aliases, positional arguments, options, defaults, validation rules, exit-code semantics, dry-run behavior, and user-facing result wording aligned.
- Before completing a change to `list`, `status`, `auth`, `config`, `doctor`, `switch`, `test`, `ping`, `add`, `delete`, or `rename`, inspect and update the corresponding parser, dispatch path, implementation, documentation, and tests for both CLIs.
- Put shared parsing and dispatch behavior in `codex_provider_lib` when practical. Keep backend-specific config, auth, model selection, and filesystem logic in the relevant provider module.
- Backend-specific differences are allowed only when the target tools genuinely require them. Document the difference and keep the remaining command shape consistent. OpenCode-only `models` commands are an explicit example.
- Add mirrored behavioral tests for both CLIs and retain the parser command-matrix test so API drift fails during validation.
- Do not mark a shared CLI change complete after validating only one executable.

## Build, Test, and Development Commands

Run commands from the repository root:

- `./codex-provider --help` and `./opencode-provider --help`: inspect both wrapper CLIs.
- `./codex-provider status` and `./opencode-provider status`: run the wrappers the same way end users do.
- `./.venv/bin/python -m pytest -q`: run the complete test suite, including CLI parity checks.
- `./.venv/bin/ruff check .`: run static checks.
- `./.venv/bin/python -m PyInstaller --clean -y codex-provider-bin.spec` and the corresponding `opencode-provider.spec` command: rebuild both standalone binaries into `dist/`.
- `./dist/codex-provider --help` and `./dist/opencode-provider --help`: confirm both packaged binaries start and expose the expected commands.

In addition to the full suite, validate the exact commands touched by your change, especially `auth detail`, `auth edit`, `config detail`, `config edit`, `switch`, and `doctor` in both CLIs.

## Coding Style & Naming Conventions

Use Python 3, 4-space indentation, and ASCII by default. Match the existing style: small helper functions, explicit exceptions, and `snake_case` names for functions and variables. Keep CLI wording stable and explicit; prefer names like `auth detail` over overloaded shortcuts.

Do not edit generated files in `build/` or `dist/` by hand.

## Testing Guidelines

Favor command-level verification with isolated state. When testing commands that read or write `~/.codex` or `~/.codex-provider`, use a temporary `HOME` to avoid touching real user data. Record the validation commands in your change notes when behavior changes are non-trivial.

## Commit & Pull Request Guidelines

History is currently minimal, so use short imperative commit messages such as `Add config detail command` or `Rebuild binary after CLI changes`. Pull requests should include a concise behavior summary, the commands used for validation, and any filesystem side effects. Include terminal screenshots only when output formatting is the change being reviewed.
