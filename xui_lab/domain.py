"""Validated domain types for the xui-lab process boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, NewType

from .errors import InputError

ForkId = NewType("ForkId", str)
Capability = NewType("Capability", str)
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{label} must be an object")
    return value


def _string(mapping: dict[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise InputError(f"{label}.{key} must be a non-empty string")
    return value


def _identifier(mapping: dict[str, Any], key: str, label: str) -> str:
    value = _string(mapping, key, label)
    if not _ID_PATTERN.fullmatch(value):
        raise InputError(f"{label}.{key} has an invalid format")
    return value


def _keys(mapping: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(mapping.keys() - allowed)
    if unknown:
        raise InputError(f"{label} contains unknown keys: {', '.join(unknown)}")


def repository_path(root: Path, value: str, label: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise InputError(f"{label} must be a repository-relative path")
    return root.joinpath(*path.parts)


@dataclass(frozen=True)
class ForkSource:
    path: Path


@dataclass(frozen=True)
class Fork:
    id: ForkId
    display_name: str
    source: ForkSource
    adapter: Path
    resource_root: PurePosixPath


@dataclass(frozen=True)
class Manifest:
    default_fork: ForkId
    forks: dict[ForkId, Fork]


@dataclass(frozen=True)
class Viewport:
    width: int
    height: int
    ui_scale: float


class Comparison(Enum):
    EQUALS = "equals"
    CONTAINS = "contains"
    EXISTS = "exists"


def parse_manifest(root: Path, raw: Any) -> Manifest:
    data = _mapping(raw, "manifest")
    _keys(data, {"$schema", "schemaVersion", "defaultFork", "forks"}, "manifest")
    if data.get("schemaVersion") != 1:
        raise InputError("manifest.schemaVersion must be 1")
    default_id = ForkId(_identifier(data, "defaultFork", "manifest"))
    entries = data.get("forks")
    if not isinstance(entries, list) or not entries:
        raise InputError("manifest.forks must be a non-empty array")

    forks: dict[ForkId, Fork] = {}
    for index, value in enumerate(entries):
        label = f"manifest.forks[{index}]"
        entry = _mapping(value, label)
        _keys(entry, {"id", "displayName", "source", "adapter", "resourceRoot"}, label)
        fork_id = ForkId(_identifier(entry, "id", label))
        if fork_id in forks:
            raise InputError(f"duplicate fork id: {fork_id}")
        source = _mapping(entry.get("source"), f"{label}.source")
        _keys(source, {"type", "path"}, f"{label}.source")
        if source.get("type") != "submodule":
            raise InputError(f"{label}.source.type must be 'submodule'")
        resource_root = PurePosixPath(_string(entry, "resourceRoot", label))
        if resource_root.is_absolute() or ".." in resource_root.parts:
            raise InputError(f"{label}.resourceRoot must be relative")
        forks[fork_id] = Fork(
            id=fork_id,
            display_name=_string(entry, "displayName", label),
            source=ForkSource(
                repository_path(
                    root,
                    _string(source, "path", f"{label}.source"),
                    f"{label}.source.path",
                )
            ),
            adapter=repository_path(
                root, _string(entry, "adapter", label), f"{label}.adapter"
            ),
            resource_root=resource_root,
        )
    if default_id not in forks:
        raise InputError("manifest.defaultFork does not name a declared fork")
    return Manifest(default_id, forks)
