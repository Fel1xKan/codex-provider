from __future__ import annotations

import json5

from lib.opencode.store import Token


def tokenize_jsonc(text: str) -> list[Token]:
    tokens: list[Token] = []
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if char in " \t\r\n":
            index += 1
            continue

        if text.startswith("//", index):
            end = text.find("\n", index)
            index = length if end == -1 else end + 1
            continue

        if text.startswith("/*", index):
            end = text.find("*/", index)
            index = length if end == -1 else end + 2
            continue

        if char in "{}:[],":
            tokens.append(Token(char, index, index + 1, char))
            index += 1
            continue

        start = index
        if char == '"':
            index += 1
            escaped = False
            while index < length:
                current = text[index]
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    index += 1
                    break
                index += 1
            tokens.append(Token("string", start, index, text[start:index]))
            continue

        while index < length and text[index] not in " \t\r\n{}:[],/#":
            index += 1
        tokens.append(Token("value", start, index, text[start:index]))

    return tokens


def object_matches(tokens: list[Token]) -> dict[int, int]:
    stack: list[int] = []
    matches: dict[int, int] = {}
    for index, token in enumerate(tokens):
        if token.kind == "{":
            stack.append(index)
        elif token.kind == "}" and stack:
            matches[stack.pop()] = index
    return matches


def object_properties(tokens: list[Token], start: int, end: int) -> dict[str, int]:
    return {
        key: value
        for key, (_, value) in object_property_entries(tokens, start, end).items()
    }


def object_property_entries(
    tokens: list[Token], start: int, end: int
) -> dict[str, tuple[int, int]]:
    result = {}
    depth = 0
    for index in range(start + 1, end):
        token = tokens[index]
        if token.kind in {"{", "["}:
            depth += 1
        elif token.kind in {"}", "]"}:
            depth -= 1
        elif (
            depth == 0
            and token.kind == "string"
            and index + 2 < end
            and tokens[index + 1].kind == ":"
        ):
            result[json5.loads(token.text)] = (index, index + 2)
    return result
