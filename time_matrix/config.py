import tomllib
from pathlib import Path
from typing import Any


def load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        return tomllib.load(file)


def section(config: dict[str, Any], name: str) -> dict[str, Any]:
    value = config.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"config section [{name}] must be a table")
    return value


def nested_section(config: dict[str, Any], *names: str) -> dict[str, Any]:
    current: dict[str, Any] = config
    path = []
    for name in names:
        path.append(name)
        value = current.get(name, {})
        if not isinstance(value, dict):
            raise ValueError(f"config section [{'.'.join(path)}] must be a table")
        current = value
    return current

