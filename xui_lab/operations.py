"""Typed runtime operations shared by Python callers and JSON scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeAlias
from uuid import UUID

from .errors import InputError


class PointerEvent(Enum):
    CLICK = "click"
    DOUBLE_CLICK = "doubleClick"


class MouseButton(Enum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class PathSelector:
    path: str

    def target(self) -> dict[str, Any]:
        return {"path": self.path}

    def describe(self) -> str:
        return f"path {self.path!r}"


@dataclass(frozen=True)
class ModelIdSelector:
    model_id: str

    def target(self) -> dict[str, Any]:
        return {"modelId": self.model_id}

    def describe(self) -> str:
        return f"model id {self.model_id!r}"


Selector: TypeAlias = PathSelector | ModelIdSelector


@dataclass(frozen=True)
class Frames:
    count: int

    def to_command(self) -> dict[str, Any]:
        return {"op": "frames", "count": self.count}


@dataclass(frozen=True)
class WaitForStable:
    consecutive_frames: int = 2
    maximum_frames: int = 60

    def to_command(self) -> dict[str, Any]:
        return {
            "op": "stable",
            "consecutiveFrames": self.consecutive_frames,
            "maximumFrames": self.maximum_frames,
        }


@dataclass(frozen=True)
class Resize:
    width: int
    height: int
    ui_scale: float | None = None

    def to_command(self) -> dict[str, Any]:
        command: dict[str, Any] = {"op": "resize", "width": self.width, "height": self.height}
        if self.ui_scale is not None:
            command["uiScale"] = self.ui_scale
        return command


@dataclass(frozen=True)
class Reload:
    def to_command(self) -> dict[str, Any]:
        return {"op": "reload"}


@dataclass(frozen=True)
class QueryTree:
    path: str | None = None

    def to_command(self) -> dict[str, Any]:
        command: dict[str, Any] = {"op": "query", "kind": "tree"}
        if self.path is not None:
            command["path"] = self.path
        return command


@dataclass(frozen=True)
class QueryValue:
    path: str

    def to_command(self) -> dict[str, Any]:
        return {"op": "query", "kind": "value", "path": self.path}


@dataclass(frozen=True)
class QueryMenus:
    def to_command(self) -> dict[str, Any]:
        return {"op": "query", "kind": "menus"}


@dataclass(frozen=True)
class QueryInventory:
    def to_command(self) -> dict[str, Any]:
        return {"op": "query", "kind": "inventory"}


@dataclass(frozen=True)
class PointerAction:
    event: PointerEvent
    button: MouseButton
    selector: Selector

    def to_command(self) -> dict[str, Any]:
        return {
            "op": "input",
            "event": self.event.value,
            "button": self.button.value,
            **self.selector.target(),
        }


@dataclass(frozen=True)
class Diagnostics:
    def to_command(self) -> dict[str, Any]:
        return {"op": "diagnostics"}


@dataclass(frozen=True)
class Capture:
    name: str | None = None
    path: str | None = None
    include_overlay: bool = False
    highlight: Selector | None = None

    def to_command(self) -> dict[str, Any]:
        command: dict[str, Any] = {"op": "capture", "includeOverlay": self.include_overlay}
        if self.name is not None:
            command["name"] = self.name
        if self.path is not None:
            command["path"] = self.path
        if self.highlight is not None:
            command["highlight"] = self.highlight.target()
        return command


RuntimeOperation: TypeAlias = (
    Frames
    | WaitForStable
    | Resize
    | Reload
    | QueryTree
    | QueryValue
    | QueryMenus
    | QueryInventory
    | PointerAction
    | Diagnostics
    | Capture
)


def path_selector(value: Any, label: str = "path") -> PathSelector:
    if not isinstance(value, str) or not value.startswith("/"):
        raise InputError(f"{label} must be an absolute XUI path")
    return PathSelector(value)


def model_id_selector(value: Any, label: str = "modelId") -> ModelIdSelector:
    if not isinstance(value, str):
        raise InputError(f"{label} must be a UUID string")
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise InputError(f"{label} must be a UUID string") from error
    return ModelIdSelector(str(parsed))


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{label} must be an object")
    return value


def _keys(command: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(command.keys() - allowed)
    if unknown:
        raise InputError(f"{label} contains unknown keys: {', '.join(unknown)}")


def _integer(value: Any, label: str, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        qualifier = "positive" if positive else "non-negative"
        raise InputError(f"{label} must be a {qualifier} integer")
    return value


def _number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise InputError(f"{label} must be positive")
    return float(value)


def _selector(command: dict[str, Any], label: str) -> Selector:
    has_path = "path" in command
    has_model_id = "modelId" in command
    if has_path == has_model_id:
        raise InputError(f"{label} must contain exactly one of path or modelId")
    if has_path:
        return path_selector(command["path"], f"{label}.path")
    return model_id_selector(command["modelId"], f"{label}.modelId")


def parse_operation(value: Any, label: str = "operation") -> RuntimeOperation:
    command = _mapping(value, label)
    op = command.get("op")
    if not isinstance(op, str) or not op:
        raise InputError(f"{label}.op must be a non-empty string")

    if op == "frames":
        _keys(command, {"op", "count"}, label)
        return Frames(_integer(command.get("count"), f"{label}.count"))
    if op == "stable":
        _keys(command, {"op", "consecutiveFrames", "maximumFrames"}, label)
        consecutive = _integer(command.get("consecutiveFrames"), f"{label}.consecutiveFrames", positive=True)
        maximum = _integer(command.get("maximumFrames"), f"{label}.maximumFrames", positive=True)
        if maximum < consecutive:
            raise InputError(f"{label}.maximumFrames must be at least consecutiveFrames")
        return WaitForStable(consecutive, maximum)
    if op == "resize":
        _keys(command, {"op", "width", "height", "uiScale"}, label)
        ui_scale = _number(command["uiScale"], f"{label}.uiScale") if "uiScale" in command else None
        return Resize(
            _integer(command.get("width"), f"{label}.width", positive=True),
            _integer(command.get("height"), f"{label}.height", positive=True),
            ui_scale,
        )
    if op == "reload":
        _keys(command, {"op"}, label)
        return Reload()
    if op == "query":
        kind = command.get("kind")
        if kind == "tree":
            _keys(command, {"op", "kind", "path"}, label)
            return QueryTree(path_selector(command["path"], f"{label}.path").path if "path" in command else None)
        if kind == "value":
            _keys(command, {"op", "kind", "path"}, label)
            return QueryValue(path_selector(command.get("path"), f"{label}.path").path)
        if kind == "menus":
            _keys(command, {"op", "kind"}, label)
            return QueryMenus()
        if kind == "inventory":
            _keys(command, {"op", "kind"}, label)
            return QueryInventory()
        raise InputError(f"{label}.kind is not a supported query: {kind!r}")
    if op == "input":
        _keys(command, {"op", "event", "button", "path", "modelId"}, label)
        try:
            event = PointerEvent(command.get("event"))
        except ValueError as error:
            raise InputError(f"{label}.event must be click or doubleClick") from error
        try:
            button = MouseButton(command.get("button"))
        except ValueError as error:
            raise InputError(f"{label}.button must be left or right") from error
        if event is PointerEvent.DOUBLE_CLICK and button is not MouseButton.LEFT:
            raise InputError(f"{label}.doubleClick supports only the left button")
        return PointerAction(event, button, _selector(command, label))
    if op == "diagnostics":
        _keys(command, {"op"}, label)
        return Diagnostics()
    if op == "capture":
        _keys(command, {"op", "name", "path", "includeOverlay", "highlight"}, label)
        name = command.get("name")
        path = command.get("path")
        if name is not None and not isinstance(name, str):
            raise InputError(f"{label}.name must be a string")
        if path is not None and not isinstance(path, str):
            raise InputError(f"{label}.path must be a string")
        include_overlay = command.get("includeOverlay", False)
        if not isinstance(include_overlay, bool):
            raise InputError(f"{label}.includeOverlay must be Boolean")
        highlight = None
        if "highlight" in command:
            highlight = _selector(_mapping(command["highlight"], f"{label}.highlight"), f"{label}.highlight")
        if include_overlay and highlight is None:
            raise InputError(f"{label}.highlight is required when includeOverlay is true")
        return Capture(name, path, include_overlay, highlight)
    raise InputError(f"{label}.op is not supported: {op}")
