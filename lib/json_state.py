#!/usr/bin/env python3
"""Top-level key store over a JSON file for the bash runtime libs: load-or-{},
then get / incr / set one key. Centralizes the load-or-default guard the gate
libs would otherwise each re-embed. Nested or list-shaped state (the inbox,
hourly budget buckets) stays in its own lib."""

import json
import sys


def _load(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _emit(value) -> str:
    return json.dumps(value) if isinstance(value, (list, dict)) else str(value)


def _coerce(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def cmd_get(path: str, key: str, default: str = "") -> int:
    data = _load(path)
    # A JSON null is "no value", not the string "None" — callers pass a default
    # precisely so they can do arithmetic on the result.
    value = data.get(key)
    print(default if value is None else _emit(value))
    return 0


def cmd_incr(path: str, key: str) -> int:
    data = _load(path)
    data[key] = int(data.get(key, 0)) + 1
    with open(path, "w") as f:
        json.dump(data, f)
    print(data[key])
    return 0


def cmd_set(path: str, key: str, value: str) -> int:
    data = _load(path)
    data[key] = _coerce(value)
    with open(path, "w") as f:
        json.dump(data, f)
    return 0


def main(argv: list[str]) -> int:
    ops = {"get": cmd_get, "incr": cmd_incr, "set": cmd_set}
    if len(argv) < 3 or argv[0] not in ops:
        print("usage: json_state <get|incr|set> <file> <key> [value|default]", file=sys.stderr)
        return 2
    return ops[argv[0]](argv[1], *argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
