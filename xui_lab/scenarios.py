"""Discover Python scenarios that drive the public Window API."""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from types import ModuleType

from .api import Window
from .domain import Capability, Viewport
from .errors import InputError

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class Scenario:
    id: str
    fork: str
    subject: str
    viewport: Viewport
    capabilities: frozenset[Capability]
    run: Callable[[Window], None]
    fixture: Path | None = None


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"_xui_lab_scenario_{path.stem}", path
    )
    if spec is None or spec.loader is None:
        raise InputError(f"cannot load Python scenario: {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        raise InputError(f"cannot load Python scenario {path}: {error}") from error
    return module


def load_scenario(root: Path, path: Path) -> Scenario:
    path = path.resolve()
    if not path.is_file() or path.suffix != ".py":
        raise InputError(f"Python scenario not found: {path}")
    value = getattr(_load_module(path), "SCENARIO", None)
    if not isinstance(value, Scenario):
        raise InputError(f"{path} must define one SCENARIO value")
    for label, identifier in (("id", value.id), ("fork", value.fork)):
        if not isinstance(identifier, str) or not _ID_PATTERN.fullmatch(identifier):
            raise InputError(f"{path} scenario {label} has an invalid format")
    if not isinstance(value.subject, str) or not value.subject:
        raise InputError(f"{path} scenario subject must be a non-empty string")
    viewport = value.viewport
    if not isinstance(viewport, Viewport):
        raise InputError(f"{path} scenario viewport must be a Viewport")
    if (
        not isinstance(viewport.width, int)
        or isinstance(viewport.width, bool)
        or viewport.width <= 0
        or not isinstance(viewport.height, int)
        or isinstance(viewport.height, bool)
        or viewport.height <= 0
        or not isinstance(viewport.ui_scale, (int, float))
        or isinstance(viewport.ui_scale, bool)
        or viewport.ui_scale <= 0
    ):
        raise InputError(f"{path} scenario viewport values must be positive")
    if not isinstance(value.capabilities, frozenset) or any(
        not isinstance(capability, str) or not capability
        for capability in value.capabilities
    ):
        raise InputError(f"{path} scenario capabilities must be non-empty strings")
    if not callable(value.run):
        raise InputError(f"{path} scenario run must be callable")

    fixture = value.fixture
    if fixture is None:
        return value
    if not isinstance(fixture, Path):
        raise InputError(f"{path} scenario fixture must be a Path")
    relative = PurePosixPath(fixture.as_posix())
    if relative.is_absolute() or ".." in relative.parts:
        raise InputError(f"{path} scenario fixture must be repository-relative")
    return replace(value, fixture=root.joinpath(*relative.parts))


def discover_scenarios(root: Path, fork: str | None = None) -> dict[str, Scenario]:
    result: dict[str, Scenario] = {}
    for path in sorted((root / "tests" / "scenarios").glob("*.py")):
        if path.name.startswith("_"):
            continue
        scenario = load_scenario(root, path)
        if fork is not None and scenario.fork != fork:
            continue
        if scenario.id in result:
            raise InputError(f"duplicate scenario id: {scenario.id}")
        result[scenario.id] = scenario
    return result
