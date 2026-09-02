"""Typed commands sent by the Python API to a fork runtime."""

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


@dataclass(frozen=True)
class ControlIdSelector:
    control_id: str

    def target(self) -> dict[str, Any]:
        return {"controlId": self.control_id}

    def describe(self) -> str:
        return f"control id {self.control_id!r}"


Selector: TypeAlias = PathSelector | ModelIdSelector | ControlIdSelector


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
class ResizeViewport:
    width: int
    height: int
    ui_scale: float | None = None

    def to_command(self) -> dict[str, Any]:
        command: dict[str, Any] = {
            "op": "resizeViewport",
            "width": self.width,
            "height": self.height,
        }
        if self.ui_scale is not None:
            command["uiScale"] = self.ui_scale
        return command


@dataclass(frozen=True)
class ResizeSubject:
    width: int
    height: int

    def to_command(self) -> dict[str, Any]:
        return {
            "op": "resizeSubject",
            "width": self.width,
            "height": self.height,
        }


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
class QueryMenus:
    def to_command(self) -> dict[str, Any]:
        return {"op": "query", "kind": "menus"}


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
class CoordinatePointerAction:
    event: PointerEvent
    button: MouseButton
    x: int
    y: int

    def to_command(self) -> dict[str, Any]:
        return {
            "op": "input",
            "event": self.event.value,
            "button": self.button.value,
            "x": self.x,
            "y": self.y,
        }


@dataclass(frozen=True)
class DragAction:
    start_x: int | None = None
    start_y: int | None = None
    end_x: int | None = None
    end_y: int | None = None
    selector: Selector | None = None
    delta_x: int | None = None
    delta_y: int | None = None

    def to_command(self) -> dict[str, Any]:
        command: dict[str, Any] = {"op": "input", "event": "drag"}
        if self.selector is not None:
            command.update(self.selector.target())
            command["deltaX"] = self.delta_x
            command["deltaY"] = self.delta_y
        else:
            command.update(
                {
                    "startX": self.start_x,
                    "startY": self.start_y,
                    "endX": self.end_x,
                    "endY": self.end_y,
                }
            )
        return command


@dataclass(frozen=True)
class KeyInput:
    key: str
    selector: Selector
    modifiers: tuple[str, ...] = ()

    def to_command(self) -> dict[str, Any]:
        return {
            "op": "input",
            "event": "key",
            "key": self.key,
            "modifiers": list(self.modifiers),
            **self.selector.target(),
        }


@dataclass(frozen=True)
class TextInput:
    text: str
    selector: Selector
    replace: bool = False

    def to_command(self) -> dict[str, Any]:
        return {
            "op": "input",
            "event": "fill" if self.replace else "text",
            "text": self.text,
            **self.selector.target(),
        }


@dataclass(frozen=True)
class Pick:
    x: int
    y: int

    def to_command(self) -> dict[str, Any]:
        return {"op": "pick", "x": self.x, "y": self.y}


@dataclass(frozen=True)
class Highlight:
    selector: Selector | None

    def to_command(self) -> dict[str, Any]:
        return {
            "op": "highlight",
            "target": self.selector.target() if self.selector is not None else None,
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
        command: dict[str, Any] = {
            "op": "capture",
            "includeOverlay": self.include_overlay,
        }
        if self.name is not None:
            command["name"] = self.name
        if self.path is not None:
            command["path"] = self.path
        if self.highlight is not None:
            command["highlight"] = self.highlight.target()
        return command


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


def control_id_selector(value: Any, label: str = "controlId") -> ControlIdSelector:
    if not isinstance(value, str) or not value:
        raise InputError(f"{label} must be a non-empty string")
    return ControlIdSelector(value)
