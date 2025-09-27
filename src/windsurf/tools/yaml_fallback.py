from __future__ import annotations

import json
from typing import Any, Tuple


def safe_load(stream: Any) -> Any:
    if hasattr(stream, "read"):
        text = stream.read()
    else:
        text = stream
    if text is None:
        return None
    lines = text.splitlines()
    data, _ = _parse_block(lines, 0, 0)
    return data


def safe_dump(data: Any, stream: Any, **_: Any) -> None:
    # Fallback: write JSON-formatted string which remains valid YAML
    dumped = json.dumps(data, ensure_ascii=False, indent=2)
    stream.write(dumped)


def _parse_block(lines: list[str], index: int, indent: int) -> Tuple[Any, int]:
    mapping: dict[str, Any] = {}
    sequence: list[Any] = []
    mode: str | None = None

    while index < len(lines):
        raw_line = lines[index]
        stripped_line = _strip_comments(raw_line).rstrip()
        if not stripped_line.strip():
            index += 1
            continue
        current_indent = len(raw_line) - len(raw_line.lstrip(" "))
        if current_indent < indent:
            break
        line = stripped_line.strip()
        if line.startswith("- "):
            if mode is None:
                mode = "list"
            elif mode != "list":
                break
            value, index = _parse_list_value(lines, index, current_indent)
            sequence.append(value)
            continue
        else:
            if mode is None:
                mode = "dict"
            elif mode != "dict":
                break
            key, value, index = _parse_mapping_entry(lines, index, current_indent)
            mapping[key] = value
    if mode == "list":
        return sequence, index
    return mapping, index


def _parse_list_value(lines: list[str], index: int, indent: int) -> Tuple[Any, int]:
    raw_line = lines[index]
    stripped = _strip_comments(raw_line).rstrip()
    entry = stripped[indent:].lstrip()[2:].strip()
    index += 1
    if entry:
        if entry.endswith(":"):
            key = entry[:-1].strip()
            nested, index = _parse_block(lines, index, indent + 2)
            return {key: nested}, index
        value, index = _parse_scalar(entry, lines, index, indent + 2)
        return value, index
    nested, index = _parse_block(lines, index, indent + 2)
    return nested, index


def _parse_mapping_entry(
    lines: list[str], index: int, indent: int
) -> Tuple[str, Any, int]:
    raw_line = lines[index]
    stripped = _strip_comments(raw_line).rstrip()
    current = stripped[indent:]
    key, _, remainder = current.partition(":")
    key = key.strip()
    remainder = remainder.strip()
    index += 1
    if remainder:
        value, index = _parse_scalar(remainder, lines, index, indent + 2)
        return key, value, index
    value, index = _parse_block(lines, index, indent + 2)
    return key, value, index


def _parse_scalar(
    token: str, lines: list[str], index: int, indent: int
) -> Tuple[Any, int]:
    if token.startswith("'") or token.startswith('"'):
        quote = token[0]
        if token.endswith(quote) and not token.endswith(f"\\{quote}"):
            return token[1:-1], index
        parts = [token[1:]]
        while index < len(lines):
            segment = _strip_comments(lines[index])
            index += 1
            if segment.rstrip().endswith(quote):
                parts.append(segment.rstrip()[:-1])
                break
            parts.append(segment.rstrip())
        return "\n".join(parts), index
    if token in {"|", "|-", ">", ">-"}:
        block_lines: list[str] = []
        while index < len(lines):
            raw_line = lines[index]
            stripped = _strip_comments(raw_line)
            if not stripped.strip():
                block_lines.append("")
                index += 1
                continue
            current_indent = len(raw_line) - len(raw_line.lstrip(" "))
            if current_indent < indent:
                break
            block_lines.append(stripped[indent:])
            index += 1
        text = "\n".join(block_lines)
        if token.startswith(">"):
            text = " ".join(line.strip() for line in text.splitlines())
        return text, index
    lower = token.lower()
    if lower in {"true", "false"}:
        return lower == "true", index
    if lower == "null":
        return None, index
    try:
        if "." in token:
            return float(token), index
        return int(token), index
    except ValueError:
        pass
    if token.startswith("[") and token.endswith("]"):
        try:
            return json.loads(token), index
        except json.JSONDecodeError:
            return token, index
    return token, index


def _strip_comments(line: str) -> str:
    result = []
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        if ch == "#" and not in_single and not in_double:
            break
        result.append(ch)
        i += 1
    return "".join(result)
