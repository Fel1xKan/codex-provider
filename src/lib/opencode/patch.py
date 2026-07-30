from __future__ import annotations

import json
from typing import Any

import json5

from lib.common.errors import SwitchError
from lib.common.jsonc_utils import (
    object_matches,
    object_properties,
    object_property_entries,
    tokenize_jsonc,
)


def _get_line_indent(text: str, start: int) -> str:
    close_line = text.rfind("\n", 0, start) + 1
    indent = ""
    for c in text[close_line:start]:
        if c in " \t":
            indent += c
        else:
            break
    return indent


def patch_default_model(text: str, target: str) -> str:
    tokens = tokenize_jsonc(text)
    if not tokens or tokens[0].kind != "{":
        raise SwitchError("OpenCode config must contain a top-level object")

    depth = 0
    root_close_index = None
    properties: list[tuple[str, int, int]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind in {"{", "["}:
            depth += 1
            index += 1
            continue
        if token.kind in {"}", "]"}:
            if token.kind == "}" and depth == 1:
                root_close_index = index
            depth -= 1
            index += 1
            continue
        if (
            depth == 1
            and token.kind == "string"
            and index + 2 < len(tokens)
            and tokens[index + 1].kind == ":"
        ):
            try:
                key = json5.loads(token.text)
            except ValueError as exc:
                raise SwitchError(f"invalid config property name: {exc}") from exc
            value_token = tokens[index + 2]
            properties.append((key, index, index + 2))
            if key == "model":
                if value_token.kind != "string":
                    raise SwitchError("top-level model must be a string")
                encoded = json.dumps(target, ensure_ascii=False)
                return text[: value_token.start] + encoded + text[value_token.end :]
        index += 1

    if root_close_index is None:
        raise SwitchError("OpenCode config top-level object is not closed")

    close = tokens[root_close_index]
    encoded = json.dumps(target, ensure_ascii=False)
    newline = "\r\n" if "\r\n" in text else "\n"
    close_indent = _get_line_indent(text, close.start)
    if properties:
        first_key = tokens[properties[0][1]]
        indent = _get_line_indent(text, first_key.start) or (close_indent + "  ")
        last_value = tokens[root_close_index - 1]
        trailing_comma = last_value.kind == ","
        if trailing_comma:
            last_value = tokens[root_close_index - 2]
        comma = "" if trailing_comma else ","
        close_line = text.rfind("\n", 0, close.start) + 1
        before = text[: last_value.end] + comma + text[last_value.end : close_line]
    else:
        indent = close_indent + "  "
        close_line = text.rfind("\n", 0, close.start) + 1
        before = text[:close_line]
    if before and not before.endswith(("\n", "\r")):
        before += newline
    return (
        before
        + f'{indent}"model": {encoded}{newline}{close_indent}'
        + text[close.start :]
    )


def patch_delete_provider(text: str, provider: str) -> str:
    tokens = tokenize_jsonc(text)
    matches = object_matches(tokens)
    root_end = matches.get(0)
    if root_end is None:
        raise SwitchError("OpenCode config must contain a top-level object")
    provider_value = object_properties(tokens, 0, root_end).get("provider")
    provider_end = matches.get(provider_value) if provider_value is not None else None
    if provider_value is None or provider_end is None:
        raise SwitchError("provider config must contain an object")
    entries = object_property_entries(tokens, provider_value, provider_end)
    entry = entries.get(provider)
    if entry is None:
        raise SwitchError(f"unknown provider '{provider}'")
    key_index, value_index = entry
    val_end = matches.get(value_index, value_index)

    start_pos = tokens[key_index].start
    end_pos = tokens[val_end].end
    if val_end + 1 < len(tokens) and tokens[val_end + 1].kind == ",":
        end_pos = tokens[val_end + 1].end

    after_line = text.find("\n", end_pos)
    if after_line != -1 and text[end_pos:after_line].strip() == "":
        end_pos = after_line + 1

    return text[:start_pos] + text[end_pos:]


def patch_rename_provider(text: str, old_name: str, new_name: str) -> str:
    tokens = tokenize_jsonc(text)
    matches = object_matches(tokens)
    root_end = matches.get(0)
    if root_end is None:
        raise SwitchError("OpenCode config must contain a top-level object")
    provider_value = object_properties(tokens, 0, root_end).get("provider")
    provider_end = matches.get(provider_value) if provider_value is not None else None
    if provider_value is None or provider_end is None:
        raise SwitchError("provider config must contain an object")
    entries = object_property_entries(tokens, provider_value, provider_end)
    if old_name not in entries:
        raise SwitchError(f"unknown provider '{old_name}'")
    key_index, _ = entries[old_name]
    token = tokens[key_index]
    encoded = json.dumps(new_name, ensure_ascii=False)
    return text[: token.start] + encoded + text[token.end :]


def patch_add_provider(
    text: str, provider: str, provider_config: dict[str, Any]
) -> str:
    tokens = tokenize_jsonc(text)
    matches = object_matches(tokens)
    root_end = matches.get(0)
    if root_end is None:
        raise SwitchError("OpenCode config must contain a top-level object")
    provider_value = object_properties(tokens, 0, root_end).get("provider")
    provider_end = matches.get(provider_value) if provider_value is not None else None

    formatted = json.dumps({provider: provider_config}, ensure_ascii=False, indent=2)
    formatted_lines = formatted.splitlines()
    inner = "\n".join(formatted_lines[1:-1])

    if provider_value is not None and provider_end is not None:
        close_token = tokens[provider_end]
        indent = _get_line_indent(text, close_token.start)
        indented_inner = "\n".join(
            (indent + "  " + line) if line.strip() else line
            for line in inner.splitlines()
        )
        entries = object_property_entries(tokens, provider_value, provider_end)
        if entries:
            last_val_index = max(v for _, v in entries.values())
            last_val_end = matches.get(last_val_index, last_val_index)
            if last_val_end + 1 < len(tokens) and tokens[last_val_end + 1].kind == ",":
                last_val_end += 1
            insert_pos = tokens[last_val_end].end
            before = text[:insert_pos] + (
                ",\n" if tokens[last_val_end].kind != "," else "\n"
            )
            after = text[insert_pos:]
            if after.lstrip().startswith(","):
                first_comma = after.find(",")
                after = after[:first_comma] + after[first_comma + 1 :]
            return before + indented_inner + "\n" + after
        else:
            before = text[: provider_value + 1] + "\n"
        return before + indented_inner + "\n" + text[close_token.start :]

    close_token = tokens[root_end]
    indent = _get_line_indent(text, close_token.start)
    indented_provider = (
        f'{indent}  "provider": {{\n'
        + "\n".join(
            (indent + "    " + line) if line.strip() else line
            for line in inner.splitlines()
        )
        + f"\n{indent}  }}"
    )
    props = object_properties(tokens, 0, root_end)
    if props:
        last_val_index = max(props.values())
        last_val_end = matches.get(last_val_index, last_val_index)
        insert_pos = tokens[last_val_end].end
        return (
            text[:insert_pos]
            + ",\n"
            + indented_provider
            + "\n"
            + text[close_token.start :]
        )
    return text[:1] + "\n" + indented_provider + "\n" + text[close_token.start :]


def patch_provider_models(
    text: str, provider: str, models: dict[str, dict[str, Any]]
) -> str:
    tokens = tokenize_jsonc(text)
    matches = object_matches(tokens)
    root_end = matches.get(0)
    if root_end is None:
        raise SwitchError("OpenCode config must contain a top-level object")
    provider_value = object_properties(tokens, 0, root_end).get("provider")
    provider_end = matches.get(provider_value) if provider_value is not None else None
    if provider_value is None or provider_end is None:
        raise SwitchError("provider config must contain an object")
    entries = object_property_entries(tokens, provider_value, provider_end)
    entry = entries.get(provider)
    if entry is None:
        raise SwitchError(f"unknown provider '{provider}'")
    _, value_index = entry
    prov_obj_end = matches.get(value_index)
    if prov_obj_end is None:
        raise SwitchError(f"provider '{provider}' config must be an object")

    prov_props = object_property_entries(tokens, value_index, prov_obj_end)
    models_entry = prov_props.get("models")
    formatted_models = json.dumps(models, ensure_ascii=False, indent=2)

    if models_entry is not None:
        _, m_val_index = models_entry
        m_val_end = matches.get(m_val_index, m_val_index)
        start_pos = tokens[m_val_index].start
        end_pos = tokens[m_val_end].end
        close_token = tokens[prov_obj_end]
        indent = _get_line_indent(text, close_token.start) + "  "
        indented_models = "\n".join(
            (indent + line) if line.strip() else line
            for line in formatted_models.splitlines()
        ).strip()
        return text[:start_pos] + indented_models + text[end_pos:]

    close_token = tokens[prov_obj_end]
    indent = _get_line_indent(text, close_token.start)
    indented_models = (
        f'{indent}  "models": '
        + "\n".join(
            (indent + "  " + line) if line.strip() else line
            for line in formatted_models.splitlines()
        ).strip()
    )
    if prov_props:
        last_val_index = max(v for _, v in prov_props.values())
        last_val_end = matches.get(last_val_index, last_val_index)
        insert_pos = tokens[last_val_end].end
        return (
            text[:insert_pos]
            + ",\n"
            + indented_models
            + "\n"
            + text[close_token.start :]
        )
    return (
        text[: value_index + 1]
        + "\n"
        + indented_models
        + "\n"
        + text[close_token.start :]
    )
