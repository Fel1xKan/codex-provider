# Contributing

Contributions should preserve the single control plane architecture in `src/lib/xpx/` while keeping target-specific adapter behavior isolated in `src/lib/xpx/adapters/`.

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
src/cli/          Unified CLI entrypoint (xpx.py)
src/lib/common/   Shared cryptography, storage, network, and upgrade helpers
src/lib/xpx/      xpx control plane core
  store/          State, provider, and account persistence (~/.xpx/)
  adapters/       Client adapters (codex, opencode, cursor, claude, agy, pi)
  models/         Model discovery, sync, and catalog enrichment
  commands/       CLI domain implementations
  accounts/       Session and OAuth account handlers
tests/            Unit, adapter, and CLI end-to-end tests
```

## Control Plane Architecture

All configuration is managed centrally in `~/.xpx/`. Native client modifications are isolated strictly to the `apply` command domain.

- The primary CLI binary is `xpx`.
- Legacy multi-call aliases transparently route to `xpx` with semantic command translation.
- New capabilities should be added directly to the appropriate `xpx` command domain or target adapter.

## Validation

Run the full suite from the repository root:

```bash
./.venv/bin/python -m ruff check .
./.venv/bin/python -m ruff format --check .
./.venv/bin/python -m pytest -q
```

Also verify that `xpx` starts and exposes its commands:

```bash
./xpx --help
./xpx status
```

Tests that read or write provider state must use an isolated temporary `HOME` (or `XPX_HOME`). Do not point tests at your real user configuration.

## Building Binaries

One build invocation creates the standalone `xpx` binary and matching SHA-256 file:

```bash
./.venv/bin/python build.py
./dist/xpx --help
./dist/xpx status
```

On Windows:

```bat
py -3 build.py
dist\xpx.exe --help
dist\xpx.exe status
```

Do not edit generated files in `build/` or `dist/` manually.

## Release Process

The package version is defined in `src/lib/common/constants.py`. GitHub Actions builds Linux (x86_64), Windows (x86_64), and macOS (Apple Silicon) binaries and publishes a release when a matching version tag is pushed. The release body comes from `CHANGELOG.md`, and `xpx upgrade` prints it before installing.

Every release entry is short and user-facing: one bullet per new capability, written for someone running the CLI. Bug fixes are not listed. CI fails on a version bump without a matching `CHANGELOG.md` section, and the test suite verifies that the release notes parser extracts notes without truncation.

```bash
# when developing
$EDITOR CHANGELOG.md          # add a bullet under "## [Unreleased]"

# when cutting a release
$EDITOR CHANGELOG.md          # move those bullets under "## [X.Y.Z] - YYYY-MM-DD"
$EDITOR src/lib/common/constants.py   # VERSION = "X.Y.Z"
./scripts/release_notes.py --check    # the same check CI runs
git tag vX.Y.Z
git push origin vX.Y.Z
```

To read a section the way a user will see it:

```bash
./scripts/release_notes.py --version 2.0.0
./xpx upgrade --notes
./xpx upgrade --check
```
