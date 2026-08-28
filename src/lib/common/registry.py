from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from lib.common.constants import VERSION


@dataclass(frozen=True)
class ArgSpec:
    names: tuple[str, ...]
    nargs: str | int | None = None
    type: Any = None
    default: Any = None
    action: str | None = None
    choices: tuple[str, ...] | None = None
    help: str | None = None
    dest: str | None = None
    metavar: str | None = None
    hidden: bool = False


@dataclass(frozen=True)
class SubcommandSpec:
    name: str
    dest: str
    handler: str = ""
    args: tuple[ArgSpec, ...] = ()
    help: str = ""
    pass_args: bool = False


@dataclass(frozen=True)
class CommandSpec:
    name: str
    handler: str
    summary: str = ""
    aliases: tuple[str, ...] = ()
    capability: str | None = None
    args: tuple[ArgSpec, ...] = ()
    subcommands: tuple[SubcommandSpec, ...] = ()


def _pos(name: str, **kwargs: Any) -> ArgSpec:
    return ArgSpec((name,), **kwargs)


def _opt(*names: str, **kwargs: Any) -> ArgSpec:
    return ArgSpec(names, **kwargs)


PROVIDER_POS = _pos(
    "provider",
    nargs="?",
    help="Provider name; defaults to current provider",
)

DRY_RUN = _opt(
    "--dry-run",
    action="store_true",
    help="Preview changes without writing files",
)
ALL_FLAG = _opt(
    "--all",
    action="store_true",
    help="Test or sync every configured provider",
)
TIMEOUT_OPT = _opt(
    "--timeout",
    type=float,
    default=30.0,
    help="HTTP timeout in seconds, default: 30",
)

MODEL_CATALOG_OPT = _opt(
    "--provider-model-catalog-json",
    help=(
        "Path to a model catalog JSON file; an empty string clears "
        "the provider field"
    ),
)

FAST_MODE_OPT = _opt(
    "--fast",
    action="store_true",
    help=(
        "Enable fast mode for this provider by writing service_tier = "
        '"priority" into the runtime config'
    ),
)

FAST_MODE_OFF = _opt(
    "--no-fast",
    action="store_true",
    help="Disable fast mode for this provider",
)

APPLY_OPT = _opt(
    "--apply",
    action="store_true",
    help=(
        "Re-render the runtime config.toml immediately when the target "
        "is active"
    ),
)

HEADER_OPT = _opt(
    "--header",
    action="append",
    metavar="KEY=VALUE",
    help=(
        "Add a provider HTTP header; repeat for multiple headers. "
        "Pass KEY= with an empty value to remove a header"
    ),
)

CONFIG_SHOW_SUB = SubcommandSpec(
    "show",
    dest="config_command",
    handler="config_detail",
    help="Show a provider config block",
    args=(
        _pos(
            "provider",
            nargs="?",
            help="Provider name; defaults to the current provider",
        ),
    ),
)

CONFIG_EDIT_SUB = SubcommandSpec(
    "edit",
    dest="config_command",
    handler="config_edit",
    help=("Open provider configuration; use auth edit to change API keys"),
    args=(
        _pos(
            "provider",
            nargs="?",
            help=("Provider name to validate; defaults to the current provider"),
        ),
    ),
)

ADD_ARGS = (
    _pos("base_url", help="Provider base_url"),
    _pos("legacy_api_key", nargs="?", hidden=True),
    _opt(
        "--api-key-stdin",
        action="store_true",
        help=("Read API key from stdin instead of a hidden interactive prompt"),
    ),
    _opt(
        "--provider",
        help="Provider name; defaults to the base_url domain",
    ),
    _opt(
        "--name",
        dest="display_name",
        help="Display name stored in provider config",
    ),
    _opt(
        "--wire-api",
        default="responses",
        help="wire_api value, default: responses",
    ),
    _opt(
        "--supports-websockets",
        choices=("true", "false"),
        help=("Set supports_websockets explicitly when supported by the backend"),
    ),
    _opt(
        "--supports-standalone-web-search",
        choices=("true", "false"),
        help=(
            "Set supports_standalone_web_search to enable Codex live "
            "web search for this provider"
        ),
    ),
)


def _add_argument(
    parser: argparse.ArgumentParser, spec: ArgSpec, *, program: str = ""
) -> None:
    kwargs: dict[str, Any] = {}
    if spec.nargs is not None:
        kwargs["nargs"] = spec.nargs
    if spec.type is not None:
        kwargs["type"] = spec.type
    if spec.default is not None:
        kwargs["default"] = spec.default
    if spec.action is not None:
        kwargs["action"] = spec.action
    if spec.choices is not None:
        kwargs["choices"] = list(spec.choices)
    if spec.help is not None:
        kwargs["help"] = spec.help.format(program=program)
    if spec.dest is not None:
        kwargs["dest"] = spec.dest
    if spec.metavar is not None:
        kwargs["metavar"] = spec.metavar
    if spec.hidden:
        kwargs["help"] = argparse.SUPPRESS
    parser.add_argument(*spec.names, **kwargs)


def build_subparser(
    subparsers: argparse._SubParsersAction,
    spec: CommandSpec,
    *,
    help_text: str,
    args: tuple[ArgSpec, ...],
    subcommands: tuple[SubcommandSpec, ...] = (),
    include_model: bool = False,
    program: str = "",
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        spec.name,
        aliases=spec.aliases,
        help=help_text,
    )
    if include_model:
        _add_argument(
            parser,
            _opt(
                "-m",
                "--model",
                help="Model ID or provider/model; prompts when ambiguous",
            ),
        )
    for arg in args:
        _add_argument(parser, arg, program=program)
    sub_parsers = None
    for sub in subcommands or spec.subcommands:
        if sub_parsers is None:
            sub_parsers = parser.add_subparsers(dest=sub.dest, required=True)
        sub_cmd = sub_parsers.add_parser(sub.name, help=sub.help)
        for arg in sub.args:
            _add_argument(sub_cmd, arg, program=program)
    return parser


def build_parser_for(backend: Any) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=backend.prog,
        description=backend.description,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for spec in backend.commands():
        help_text = backend.command_help.get(spec.name, spec.summary)
        args = backend.command_args.get(spec.name, spec.args)
        subcommands = backend.command_subcommands.get(spec.name, spec.subcommands)
        include_model = spec.name == "switch" and backend.switch_include_model
        build_subparser(
            subparsers,
            spec,
            help_text=help_text.format(program=backend.prog),
            args=args,
            subcommands=subcommands,
            include_model=include_model,
            program=backend.prog,
        )
    return parser


COMMON_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec(
        "list",
        handler="list",
        summary="List providers from provider config",
    ),
    CommandSpec(
        "status",
        handler="status",
        summary="Show current provider and configuration",
    ),
    CommandSpec(
        "auth",
        handler="auth",
        summary="Inspect or edit provider authentication data",
        subcommands=(
            SubcommandSpec(
                "show",
                dest="auth_command",
                handler="auth_detail",
                help="Show auth metadata without printing credential values",
                args=(
                    _pos(
                        "provider",
                        nargs="?",
                        help="Provider name; defaults to the current scope",
                    ),
                ),
            ),
            SubcommandSpec(
                "edit",
                dest="auth_command",
                handler="auth_edit",
                help=(
                    "Open provider authentication data, including API keys, "
                    "in the editor"
                ),
                args=(
                    _pos(
                        "provider",
                        nargs="?",
                        help="Provider name; defaults to the current scope",
                    ),
                ),
            ),
        ),
    ),
    CommandSpec(
        "config",
        handler="config",
        summary="Inspect or edit provider configuration; API keys use auth",
        subcommands=(CONFIG_SHOW_SUB, CONFIG_EDIT_SUB),
    ),
    CommandSpec(
        "doctor",
        handler="doctor",
        summary="Validate provider configuration and authentication data",
        args=(
            _opt(
                "--fix",
                action="store_true",
                help="Apply supported automatic repairs",
            ),
        ),
    ),
    CommandSpec(
        "test",
        handler="test",
        summary="Test a provider or direct base_url with /models",
        args=(
            _pos(
                "args",
                nargs="*",
                metavar="provider|base_url",
                help="No args/current provider, provider name, or direct base_url",
            ),
            ALL_FLAG,
            _opt(
                "--api-key-stdin",
                action="store_true",
                help="Read API key from stdin for direct base_url tests",
            ),
            TIMEOUT_OPT,
        ),
    ),
    CommandSpec(
        "ping",
        handler="ping",
        summary="Test providers with a minimal {program} command",
        aliases=("p",),
        args=(
            PROVIDER_POS,
            _opt(
                "--all",
                action="store_true",
                help=(
                    "Ping every configured provider and print an availability summary"
                ),
            ),
            _opt(
                "--timeout",
                type=float,
                default=120.0,
                help="{program} command timeout in seconds, default: 120",
            ),
            _opt("-m", "--model", help="Override model for this ping"),
            _opt(
                "--prompt",
                default="say hi",
                help='Prompt for the ping, default: "say hi"',
            ),
        ),
    ),
    CommandSpec(
        "switch",
        handler="switch",
        summary="Switch the active provider",
        args=(
            _pos(
                "provider",
                nargs="?",
                help="Provider name; opens an interactive picker when omitted",
            ),
            DRY_RUN,
        ),
    ),
    CommandSpec(
        "add",
        handler="add",
        summary="Add a provider config and auth entry",
        args=(*ADD_ARGS, DRY_RUN),
    ),
    CommandSpec(
        "delete",
        handler="delete",
        summary="Delete a provider config",
        args=(
            _pos("provider", help="Provider name to delete"),
            _opt(
                "--full",
                action="store_true",
                help="Also remove provider authentication data",
            ),
            DRY_RUN,
        ),
    ),
    CommandSpec(
        "rename",
        handler="rename",
        summary="Rename a provider",
        args=(
            _pos("old_provider", help="Existing provider name"),
            _pos("new_provider", help="New provider name"),
            DRY_RUN,
        ),
    ),
    CommandSpec(
        "export",
        handler="export",
        summary=(
            "Export configuration and authentication data to a JSON file or stdout"
        ),
        args=(
            _pos(
                "file",
                nargs="?",
                help="Output file path; prints to stdout if omitted or '-'",
            ),
        ),
    ),
    CommandSpec(
        "import",
        handler="import",
        summary=(
            "Import configuration and authentication data from a JSON file or stdin"
        ),
        args=(
            _pos(
                "file",
                nargs="?",
                help="Input file path; reads from stdin if omitted or '-'",
            ),
            DRY_RUN,
        ),
    ),
)
