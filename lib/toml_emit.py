"""Minimal TOML emitter for dAImon's daemon.toml shapes (scalars, inline tables,
arrays, plus [section] headers). Shared by config.py and the sync compiler."""

from __future__ import annotations

import json


def emit_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        # JSON's string escaping (\", \\, \n, \uXXXX) is valid in a TOML basic
        # string, so quotes, backslashes and newlines survive a round trip.
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k} = {emit_value(val)}" for k, val in v.items()) + " }"
    if isinstance(v, list):
        return "[" + ", ".join(emit_value(x) for x in v) + "]"
    raise TypeError(f"cannot emit {v!r}")


def emit_kv(key: str, value) -> str:
    return f"{key} = {emit_value(value)}"


def _section_lines(name: str, table: dict) -> list[str]:
    return [f"[{name}]"] + [emit_kv(k, v) for k, v in table.items()]


def dump_sections(sections: dict[str, dict]) -> str:
    blocks = [_section_lines(name, table) for name, table in sections.items() if table]
    return "\n\n".join("\n".join(b) for b in blocks) + "\n"


def _bracket_depth(line: str) -> int:
    """Net `[` minus `]` on a line, ignoring strings and comments."""
    depth, quote, i = 0, "", 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            break
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        i += 1
    return depth


def _is_table_header(line: str) -> bool:
    s = line.strip()
    return s.startswith("[") and not s.startswith("[[") and s.endswith("]")


def set_key_text(text: str, table: str, key: str, value, comment: str = "") -> str:
    """Set `key = value` in top-level table [table] of a TOML document's text,
    keeping every comment and other setting. Replaces the key's existing value
    (a multi-line array too) or adds the key at the end of the table, creating
    the table at the end of the file when absent. A `comment` goes on its own
    line just above the key."""
    new_line = emit_kv(key, value)
    if isinstance(value, list) and len(new_line) > 88:  # one item per line
        new_line = "\n".join([f"{key} = [", *(f"  {emit_value(v)}," for v in value), "]"])
    if comment:
        new_line = f"# {comment}\n{new_line}"
    lines = text.splitlines()
    out: list[str] = []
    in_table = done = False
    i = 0
    while i < len(lines):
        ln = lines[i]
        if _is_table_header(ln) and _bracket_depth(ln) == 0:
            if in_table and not done:
                while out and not out[-1].strip():
                    out.pop()
                out += [new_line, ""]
                done = True
            in_table = ln.strip()[1:-1].strip() == table
        elif in_table and not done and ln.split("=", 1)[0].strip() == key and "=" in ln:
            depth = _bracket_depth(ln.split("=", 1)[1])
            while depth > 0 and i + 1 < len(lines):  # skip a multi-line value
                i += 1
                depth += _bracket_depth(lines[i])
            out.append(new_line)
            done = True
            i += 1
            continue
        out.append(ln)
        i += 1
    if not done:
        if in_table:
            while out and not out[-1].strip():
                out.pop()
            out.append(new_line)
        else:
            if out and out[-1].strip():
                out.append("")
            out += [f"[{table}]", new_line]
    return "\n".join(out) + "\n"
