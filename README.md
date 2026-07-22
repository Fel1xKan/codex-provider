# codex-provider / opencode-provider

This repository builds two provider managers with the same CLI shape:

- `codex-provider` manages Codex's TOML runtime config and auth snapshots.
- `opencode-provider` manages OpenCode's JSON/JSONC provider config and auth.

Both commands share the same `list`, `status`, `switch`, `test`, `ping`, and
`p` command forms. Their backend only differs in the config/auth file format,
locations, and the target CLI used by `ping`.

OpenCode keeps all custom provider definitions in its global JSON/JSONC config
and all `/connect` credentials in a separate auth file. This tool leaves those
provider definitions and credentials in place. A switch only updates the
top-level `model` value to `provider/model`, which is OpenCode's native default
model mechanism.

## Safety properties

- Provider API keys and auth values are never printed.
- Switches preserve unrelated global config values.
- JSONC comments and trailing commas are preserved.
- Config writes are atomic and retain existing POSIX permissions.
- A provider excluded by `enabled_providers` or `disabled_providers` cannot be
  selected accidentally.
- `switch --dry-run` does not modify the config.

## Installation

```bash
pipx install .
opencode-provider --version
```

For development:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements-dev.txt
./opencode-provider --help
```

## Commands

```bash
codex-provider list
codex-provider status
opencode-provider list
opencode-provider status

codex-provider test
codex-provider test --all
codex-provider ping
codex-provider ping ggniao --model gpt-5

opencode-provider test
opencode-provider test --all
opencode-provider ping
opencode-provider ping foye --model grok-4.5

opencode-provider models list foye
opencode-provider models sync foye
opencode-provider models sync --all
opencode-provider models sync foye --dry-run

opencode-provider switch
opencode-provider switch foye
opencode-provider switch bailian-token-plan-personal --model qwen3-coder-plus
opencode-provider switch bailian-token-plan-personal \
  --model bailian-token-plan-personal/qwen3-coder-plus
opencode-provider switch foye --dry-run
opencode-provider delete foye
opencode-provider delete foye --full
opencode-provider delete foye --dry-run
```

`list` reports the custom providers declared in the global OpenCode config,
their configured model counts, whether credentials are present, and whether
OpenCode provider filters allow them.

`switch` sets the global config's top-level `model` field. When the target has
one model, that model is selected automatically. When the current model ID also
exists on the target, the model ID is retained. Otherwise an interactive
terminal presents a model menu; in non-interactive use, pass `--model`.

For `codex-provider`, `test` probes the configured provider's `/models` endpoint
and `ping` invokes `codex exec`. For `opencode-provider`, the same commands
probe the OpenCode provider endpoint and `ping` invokes `opencode run` with the
selected `provider/model`.

`models list` fetches model IDs from an OpenAI-compatible provider's
`options.baseURL/models` endpoint without changing config. `models sync` adds
new IDs to `provider.<id>.models` and keeps existing model metadata unchanged.
It never removes models. Use `--all` to continue through every configured
provider and return status 1 if any provider cannot be queried. Credentials are
read from `options.apiKey` or OpenCode's `~/.local/share/opencode/auth.json`;
API keys are never printed.

Running `switch` without a provider opens the existing provider picker. In a
non-interactive environment, provide the provider explicitly.

`delete` removes the provider block from the global OpenCode config while
preserving unrelated JSONC content. It keeps the OpenCode auth entry by default;
pass `--full` to remove that entry too. The current provider cannot be deleted
until another provider is selected.

## OpenCode files

The tool follows the same XDG locations as OpenCode on macOS and Linux:

```text
~/.config/opencode/opencode.jsonc
~/.config/opencode/opencode.json
~/.config/opencode/config.json
~/.local/share/opencode/auth.json
```

For global config, the first existing filename in the order above is used.
`XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and `XDG_STATE_HOME` are respected.

Only providers explicitly defined under the global config's `provider` object
are switchable because OpenCode requires a concrete model ID. Built-in
providers that exist only in `auth.json` are not listed by this tool.

Project-level `opencode.json` files have higher precedence than the global
config. If a project sets its own top-level `model`, that project setting will
continue to override a global switch.

## Build

One build invocation produces both standalone binaries:

```bash
python build.py
./build.sh
./dist/codex-provider --help
./dist/opencode-provider --help
```

On Windows:

```bat
py -3 build.py
build.cmd
dist\opencode-provider.exe --help
dist\codex-provider.exe --help
```

Use `--target codex` or `--target opencode` to build only one target.
`build.py` verifies both binary versions and writes a matching `.sha256` file.

## Validation

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest
python build.py
```
