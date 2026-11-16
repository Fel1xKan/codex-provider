"""Model catalogue commands: sync, list, set."""

from __future__ import annotations

import argparse

from lib.xpx.commands.cmd_models import run_models_list, run_models_set, run_models_sync


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register the models subcommands."""
    p_models = subparsers.add_parser(
        "models", help="Model capabilities and preferences"
    )
    mod_sub = p_models.add_subparsers(dest="models_action", metavar="<action>")

    p_mod_sync = mod_sub.add_parser("sync", help="Synchronize remote models")
    p_mod_sync.add_argument("provider", help="Provider name")
    p_mod_sync.add_argument(
        "--force",
        action="store_true",
        help="Force reset reasoning ladders to catalog default",
    )
    p_mod_sync.set_defaults(func=run_models_sync)

    p_mod_list = mod_sub.add_parser("list", help="List cached or remote models")
    p_mod_list.add_argument("provider", nargs="?", help="Provider name")
    p_mod_list.add_argument(
        "--remote", action="store_true", help="Fetch directly from remote endpoint"
    )
    p_mod_list.set_defaults(func=run_models_list)

    p_mod_set = mod_sub.add_parser(
        "set",
        help="Add or update a model in a provider catalog",
        description=(
            "Create or update a model entry for a provider. Creating and "
            "updating were separate commands (`models add` / `models set`) with "
            "different flags even though both upsert; they are now one command "
            "with an explicit <provider> <model> order."
        ),
    )
    p_mod_set.add_argument("provider", help="Provider name")
    p_mod_set.add_argument("model", help="Model ID")
    p_mod_set.add_argument("--display-name", help="Display name for the model")
    p_mod_set.add_argument(
        "--default", action="store_true", help="Mark as provider default model"
    )
    p_mod_set.add_argument(
        "--context", type=int, help="Context window limit (e.g. 128000)"
    )
    p_mod_set.add_argument(
        "--max-output", type=int, help="Max output tokens limit (e.g. 8192)"
    )
    p_mod_set.add_argument(
        "--effort",
        help=(
            "Supported reasoning effort / thinking levels "
            "(e.g. 'high' or 'low,medium,high')"
        ),
    )
    p_mod_set.add_argument(
        "--modalities", help="Comma-separated input modalities (e.g. text,image)"
    )
    p_mod_set.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing model configuration instead of merging",
    )
    p_mod_set.set_defaults(func=run_models_set)
