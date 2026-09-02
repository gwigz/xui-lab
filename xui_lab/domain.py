"""Validated domain types for the xui-lab process boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any, NewType

from .errors import InputError


ForkId = NewType("ForkId", str)
ScenarioId = NewType("ScenarioId", str)
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


def _validate_capture_step(step: dict[str, Any], label: str) -> None:
    if "path" in step:
        value = step["path"]
        if not isinstance(value, str) or not value:
            raise InputError(f"{label}.path must be a non-empty capture path")
        paths = (PurePosixPath(value), PureWindowsPath(value))
        if any(path.is_absolute() or path.drive or ".." in path.parts for path in paths):
            raise InputError(f"{label}.path capture must stay beneath the scenario artifact directory")
    if "name" in step:
        value = step["name"]
        if not isinstance(value, str) or not value:
            raise InputError(f"{label}.name must be a non-empty capture name")
        if value in {".", ".."} or PureWindowsPath(value).drive or "/" in value or "\\" in value:
            raise InputError(f"{label}.name must not create capture subdirectories")


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


@dataclass(frozen=True)
class RuntimeStep:
    op: str
    payload: dict[str, Any]
    save_as: str | None


@dataclass(frozen=True)
class AssertionStep:
    source: str
    pointer: str
    comparison: Comparison
    expected: Any


ScenarioStep = RuntimeStep | AssertionStep


@dataclass(frozen=True)
class Scenario:
    id: ScenarioId
    fork: ForkId
    subject: str
    fixture: Path | None
    viewport: Viewport
    required_capabilities: frozenset[Capability]
    steps: tuple[ScenarioStep, ...]


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
            source=ForkSource(repository_path(root, _string(source, "path", f"{label}.source"), f"{label}.source.path")),
            adapter=repository_path(root, _string(entry, "adapter", label), f"{label}.adapter"),
            resource_root=resource_root,
        )
    if default_id not in forks:
        raise InputError("manifest.defaultFork does not name a declared fork")
    return Manifest(default_id, forks)


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise InputError(f"{label} must be a positive integer")
    return value


def parse_scenario(root: Path, raw: Any, label: str = "scenario") -> Scenario:
    data = _mapping(raw, label)
    _keys(data, {"$schema", "schemaVersion", "id", "fork", "subject", "fixture", "viewport", "requires", "steps"}, label)
    if data.get("schemaVersion") != 1:
        raise InputError(f"{label}.schemaVersion must be 1")

    viewport_data = _mapping(data.get("viewport"), f"{label}.viewport")
    _keys(viewport_data, {"width", "height", "uiScale"}, f"{label}.viewport")
    ui_scale = viewport_data.get("uiScale", 1.0)
    if not isinstance(ui_scale, (int, float)) or isinstance(ui_scale, bool) or ui_scale <= 0:
        raise InputError(f"{label}.viewport.uiScale must be positive")
    viewport = Viewport(
        _positive_int(viewport_data.get("width"), f"{label}.viewport.width"),
        _positive_int(viewport_data.get("height"), f"{label}.viewport.height"),
        float(ui_scale),
    )

    requires = data.get("requires", [])
    if not isinstance(requires, list) or any(not isinstance(value, str) or not value for value in requires):
        raise InputError(f"{label}.requires must be an array of non-empty strings")
    if len(requires) != len(set(requires)):
        raise InputError(f"{label}.requires must not contain duplicates")

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise InputError(f"{label}.steps must be a non-empty array")
    steps: list[ScenarioStep] = []
    for index, value in enumerate(raw_steps):
        step_label = f"{label}.steps[{index}]"
        step = _mapping(value, step_label)
        op = _string(step, "op", step_label)
        if op == "assert":
            _keys(step, {"op", "source", "pointer", "comparison", "expected"}, step_label)
            comparison_text = step.get("comparison", "equals")
            try:
                comparison = Comparison(comparison_text)
            except ValueError as error:
                allowed = ", ".join(value.value for value in Comparison)
                raise InputError(f"{step_label}.comparison must be one of: {allowed}") from error
            if comparison is not Comparison.EXISTS and "expected" not in step:
                raise InputError(f"{step_label}.expected is required for {comparison.value}")
            pointer = step.get("pointer", "")
            if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
                raise InputError(f"{step_label}.pointer must be an RFC 6901 JSON pointer")
            steps.append(AssertionStep(_string(step, "source", step_label), pointer, comparison, step.get("expected")))
            continue
        if op == "capture":
            _validate_capture_step(step, step_label)
        save_as = step.get("saveAs")
        if save_as is not None and (not isinstance(save_as, str) or not save_as):
            raise InputError(f"{step_label}.saveAs must be a non-empty string")
        payload = dict(step)
        payload.pop("saveAs", None)
        steps.append(RuntimeStep(op, payload, save_as))

    fixture_value = data.get("fixture")
    fixture = None
    if fixture_value is not None:
        if not isinstance(fixture_value, str) or not fixture_value:
            raise InputError(f"{label}.fixture must be a non-empty path")
        fixture = repository_path(root, fixture_value, f"{label}.fixture")

    return Scenario(
        ScenarioId(_identifier(data, "id", label)),
        ForkId(_identifier(data, "fork", label)),
        _string(data, "subject", label),
        fixture,
        viewport,
        frozenset(Capability(value) for value in requires),
        tuple(steps),
    )
