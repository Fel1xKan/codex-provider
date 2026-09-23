# Changelog

Release notes for this project. `xpx upgrade` prints the newest notes before it
replaces the binary, so keep them short and user-facing: one line per new
capability, no implementation detail and no bug-fix entries.

Add your entry under `## [Unreleased]` while a change is in review; the release
workflow moves it to the version being tagged.

## [Unreleased]

## [2.2.2] - 2026-09-23

- Automatically generate and emit `models.json` catalog for Codex CLI upon `xpx apply`.
- Configure `model_catalog_json` in `~/.codex/config.toml` to support session resumption and model switching in `/models`.
- Retain previously active models in `models.json` to prevent session resume lookup failures.
- Automatically refresh Codex `models.json` when synchronizing or updating provider models.

## [2.2.1] - 2026-09-22

- Smooth screen transitions with page-level clearing across interactive wizard steps and submenus.
- Fix cursor alignment and indentation jitter when moving through interactive selection items.
- Fix Pi CLI agent package reference to `@earendil-works/pi-coding-agent` with native update support.
- Silent exit when quitting interactive control plane wizard.

## [2.2.0] - 2026-09-22

- Display installed CLI version of each agent in `xpx status` dashboard.
- New `xpx agent` command domain for listing, installing, and updating target agent CLIs.
- Support `xpx agent install [target] [--all]` to automate installation of missing agent CLIs.
- Support `xpx agent update [target] [--all]` to update installed agent CLIs.
- Interactive Agent Management wizard in `xpx` main menu with full i18n support.

## [2.1.0] - 2026-09-21

- Interactive control plane wizard (`xpx` / `xpx interactive`) with live status dashboard and fuzzy search.
- Multi-language localization support with Chinese and English interface options.
- Codex capability isolation restricting `--fast`, `--web-search`, and `--wire-api` strictly to Codex.
- Claude Code adapter auto-normalizes custom proxy base URLs and syncs subagent models.
- Enhanced interactive model listing and multi-target batch application.

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
