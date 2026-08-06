# Contributing

Contributions should preserve the shared CLI contract while keeping
backend-specific filesystem and authentication behavior isolated in the
corresponding provider module.

## Development Setup

Python 3.11 or newer is required.

```bash
git clone https://github.com/Fel1xKan/codex-provider.git
cd codex-provider
python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[dev,build]"
```

On Windows, replace `./.venv/bin/python` with `.venv\Scripts\python.exe`.

## Repository Layout

```text
src/cli/        CLI entry points
src/lib/common/ Shared parsing, network, storage, and platform helpers
src/lib/codex/  Codex-specific behavior
src/lib/opencode/ OpenCode-specific behavior
src/lib/agy/    Antigravity-specific behavior
tests/          Command, storage, network, and parity tests
```

The shell launchers in the repository root execute the Python entry points.
PyInstaller specifications produce the standalone binaries in `dist/`.

## CLI Consistency

Changes to a shared command must update both `codex-provider` and
`opencode-provider` in the same change. Keep command names, aliases, positional
arguments, options, defaults, validation rules, exit codes, dry-run behavior,
and user-facing wording aligned.

Before completing changes to shared commands, inspect the parser, dispatch
path, implementation, documentation, and mirrored tests for both CLIs.
OpenCode-only `models` behavior and Antigravity account workflows are valid
backend-specific extensions.

## Validation

Run the full suite from the repository root:

```bash
./.venv/bin/python -m ruff check .
./.venv/bin/python -m ruff format --check .
./.venv/bin/python -m pytest -q
```

Also verify that every wrapper starts and exposes its intended commands:

```bash
./codex-provider --help
./opencode-provider --help
./agy-provider --help
```

For behavior changes, validate the exact commands touched. Shared command work
should cover both Codex and OpenCode variants, especially `auth detail`,
`auth edit`, `config detail`, `config edit`, `switch`, and `doctor`.

Tests that read or write provider state must use an isolated temporary `HOME`
and, where relevant, temporary XDG directories. Do not point tests at your real
Codex, OpenCode, or Antigravity configuration.

## Building Binaries

One build invocation creates all three standalone binaries and matching
SHA-256 files:

```bash
./.venv/bin/python build.py
./build.sh
./dist/codex-provider --help
./dist/opencode-provider --help
./dist/agy-provider --help
```

On Windows:

```bat
py -3 build.py
build.cmd
dist\codex-provider.exe --help
dist\opencode-provider.exe --help
dist\agy-provider.exe --help
```

Use `--target codex`, `--target opencode`, `--target agy`, or `--target cursor`
with `build.py` to build one target. Do not edit generated files in `build/` or
`dist/` manually.

## Release Process

The package version is defined in `src/lib/common/constants.py`. GitHub Actions
builds Linux (x86_64), Windows (x86_64), and macOS (Apple Silicon) binaries and
publishes a release when a matching version tag is pushed.

```bash
git tag v0.6.0
git push origin v0.6.0
```

The Release workflow can also be run manually. A release fails if its tag does
not match the package version. Every staged binary receives a matching
`.sha256` checksum file.

## Pull Requests

Keep changes focused and use short imperative commit messages. A pull request
should summarize behavior changes, list validation commands, and identify any
filesystem side effects. Include terminal screenshots only when output
formatting is the behavior under review.
