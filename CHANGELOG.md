# Changelog

Release notes for this project. `xpx upgrade` prints the newest notes before it
replaces the binary, so keep them short and user-facing: one line per new
capability, no implementation detail and no bug-fix entries.

Add your entry under `## [Unreleased]` while a change is in review; the release
workflow moves it to the version being tagged.

## [Unreleased]

## [2.0.0] - 2026-09-20

- Unified single control plane CLI `xpx` managing Codex, OpenCode, Claude, Cursor, Antigravity, and Pi.
- Dedicated `apply` engine isolating client config rendering with multi-tier overrides and memory persistence.
- Centralized model catalog integration, auto-syncing capabilities, contexts, and reasoning tiers.
- Unified account lifecycle management for OAuth and session-based agent accounts.
- Comprehensive `doctor` health inspection, repairing orphan state and dangling configurations.
- Concurrent `ping --all` testing connectivity and real prompt latency across configured targets.
- Automatic one-time migration from legacy configurations to unified `~/.xpx/`.

## [1.5.4] - 2026-09-20

- `upgrade` shows what's new before it installs, and `upgrade --notes`
  prints the newest notes on their own.
- `/model` offers each model's real reasoning levels, including `medium`,
  `xhigh`, `max`, and `ultra` where the model supports them, instead of only
  `low`, `high`, and `max`. Levels for 116 models come from vendor docs.
- Models with only a thinking switch are labelled that way, and models without
  a thinking mode no longer ask you to choose a level.
- `models sync --force` resets a provider's reasoning levels, and
  `models update --set supported_reasoning_levels=...` edits one model.
- New Qwen models in the shared catalog, such as `qwen3.8-max`,
  `qwen3.8-flash`, `qwen3.7-plus`, `qwen3-vl-plus`, and `qwq-plus`.

## [1.5.3] - 2026-09-11

- `upgrade` reports download and install progress.

## [1.5.2] - 2026-09-10

- `export` converts OpenAI-compatible provider settings into other tools'
  import formats.

## [1.5.1] - 2026-09-09

- Model metadata is refreshed from the versioned catalog in this repository,
  filling in display name, context, and output limits for models that
  providers report by ID only.

## [1.5.0] - 2026-09-08

- `models list`, `models sync`, `models set`, and `models update` for Codex,
  OpenCode, and Claude, with per-provider catalog files.
