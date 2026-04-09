from __future__ import annotations

import os
import re
from pathlib import Path

_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _expand(value: str, scope: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2)
        return scope.get(key, os.environ.get(key, ""))

    prev = None
    current = value
    for _ in range(5):
        if current == prev:
            break
        prev = current
        current = _VAR_PATTERN.sub(repl, current)
    return current


def load_env_file(dotenv_path: str | Path) -> None:
    path = Path(dotenv_path)
    if not path.exists():
        return

    scoped: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = _strip_quotes(val)
        val = _expand(val, scoped)
        scoped[key] = val
        os.environ.setdefault(key, val)
