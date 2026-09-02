"""Playwright-style control of one xui-lab runtime process."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from .assertions import check_observation
from .domain import Capability, Comparison, Fork, Viewport
from .errors import (
    AssertionFailure,
    CapabilityError,
    InputError,
    RuntimeFailure,
)
from .io import git_commit, read_json, write_json
from .operations import (
    Capture,
    ControlIdSelector,
    CoordinatePointerAction,
    Diagnostics,
    DragAction,
    Frames,
    Highlight,
    KeyInput,
    MouseButton,
    PathSelector,
    Pick,
    PointerAction,
    PointerEvent,
    QueryMenus,
    QueryTree,
    Reload,
    ResizeSubject,
    ResizeViewport,
    Selector,
    TextInput,
    WaitForStable,
    control_id_selector,
    model_id_selector,
    path_selector,
)
from .protocol import RuntimeProcess


def artifact_directory(root: Path, artifact_id: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / artifact_id).resolve()
    if candidate.parent != resolved_root:
        raise InputError(f"artifact directory escapes artifact root: {artifact_id}")
    return candidate


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeFailure(f"{label} must be an object")
    return value


def _tree_nodes(tree: Any) -> list[dict[str, Any]]:
    if not isinstance(tree, dict):
        return []
    nodes = [tree]
    children = tree.get("children", [])
    if isinstance(children, list):
        for child in children:
            nodes.extend(_tree_nodes(child))
    return nodes


def _node_state(tree: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for node in _tree_nodes(tree):
        path = node.get("path")
        control_id = node.get("control_id")
        identity = (
            f"{path} [{control_id}]"
            if isinstance(path, str) and isinstance(control_id, str)
            else path
        )
        if isinstance(identity, str):
            result[identity] = {
                key: value for key, value in node.items() if key != "children"
            }
    return result


@dataclass(frozen=True)
class Control:
    selector: Selector
    info: dict[str, Any]

    @property
    def control_id(self) -> str:
        return str(self.info.get("control_id", ""))

    @property
    def path(self) -> str:
        return str(self.info.get("path", ""))

    @property
    def runtime_class(self) -> str:
        return str(self.info.get("class", ""))

    @property
    def source_file(self) -> str:
        return str(self.info.get("source_file", ""))

    @property
    def source_line(self) -> int:
        value = self.info.get("source_line", 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0


@dataclass(frozen=True)
class ActionResult:
    action: str
    data: dict[str, Any]

    @property
    def handled(self) -> bool:
        return self.data.get("handled") is True

    def expect_handled(self, expected: bool = True) -> ActionResult:
        check_observation(
            self.action, self.data, "/handled", Comparison.EQUALS, expected
        )
        return self


class Lab:
    def __init__(
        self,
        repository_root: Path,
        fork: Fork,
        viewer_source: Path,
        executable: Path,
        artifact_root: Path,
    ):
        self.repository_root = repository_root
        self.fork = fork
        self.viewer_source = viewer_source
        self.executable = executable
        self.artifact_root = artifact_root

    def open(
        self,
        *,
        artifact_id: str,
        subject: str,
        viewport: Viewport,
        capabilities: frozenset[Capability],
        fixture: Path | None = None,
        stability: WaitForStable = WaitForStable(),
        interactive: bool = False,
    ) -> Window:
        artifact_dir = artifact_directory(self.artifact_root, artifact_id)
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True)
        runtime = RuntimeProcess(
            self.executable,
            artifact_dir / "runtime.log",
            mode="interactive" if interactive else "scenario",
        )
        window = Window(runtime, artifact_dir, stability)
        try:
            fixture_data = read_json(fixture) if fixture else None
            initialize = {
                "op": "initialize",
                "fork": self.fork.id,
                "forkCommit": git_commit(self.viewer_source),
                "resourceRoot": str(
                    self.viewer_source.joinpath(*self.fork.resource_root.parts)
                ),
                "subject": subject,
                "viewport": {
                    "width": viewport.width,
                    "height": viewport.height,
                    "uiScale": viewport.ui_scale,
                },
                "fixture": fixture_data,
                "artifactDir": str(artifact_dir),
            }
            hello = window._request(initialize)
            supported = _mapping(hello, "initialize result").get(
                "supportedCapabilities"
            )
            if not isinstance(supported, list) or any(
                not isinstance(value, str) for value in supported
            ):
                raise RuntimeFailure(
                    "initialize response has invalid supportedCapabilities"
                )
            missing = sorted(str(value) for value in capabilities - set(supported))
            if missing:
                raise CapabilityError(
                    f"runtime is missing capabilities: {', '.join(missing)}"
                )

            installed = window._request(
                {"op": "installCapabilities", "capabilities": sorted(capabilities)}
            )
            installed_map = _mapping(installed, "installCapabilities result")
            installed_capabilities = installed_map.get("capabilities")
            event_apis = installed_map.get("eventApis")
            input_operations = installed_map.get("inputOperations")
            if not isinstance(installed_capabilities, list) or any(
                not isinstance(value, str) for value in installed_capabilities
            ):
                raise RuntimeFailure(
                    "installCapabilities response has invalid capabilities"
                )
            if not isinstance(event_apis, dict):
                raise RuntimeFailure(
                    "installCapabilities response has invalid eventApis"
                )
            if not isinstance(input_operations, list) or any(
                not isinstance(value, str) for value in input_operations
            ):
                raise RuntimeFailure(
                    "installCapabilities response has invalid inputOperations"
                )
            missing = sorted(
                str(value) for value in capabilities - set(installed_capabilities)
            )
            if missing:
                raise CapabilityError(
                    f"runtime did not install capabilities: {', '.join(missing)}"
                )
            window._install(
                frozenset(Capability(value) for value in installed_capabilities),
                event_apis,
                frozenset(input_operations),
            )
            return window
        except BaseException as error:
            window._finish(error)
            raise


class Window:
    def __init__(
        self, runtime: RuntimeProcess, artifact_dir: Path, stability: WaitForStable
    ):
        self.runtime = runtime
        self.artifact_dir = artifact_dir
        self.stability = stability
        self.trace: list[dict[str, Any]] = []
        self.capabilities: frozenset[Capability] = frozenset()
        self.event_apis: dict[str, Any] = {}
        self.input_operations: frozenset[str] = frozenset()
        self._finished = False

    def _install(
        self,
        capabilities: frozenset[Capability],
        event_apis: dict[str, Any],
        input_operations: frozenset[str],
    ) -> None:
        self.capabilities = capabilities
        self.event_apis = event_apis
        self.input_operations = input_operations

    def _request(self, command: dict[str, Any]) -> Any:
        response = self.runtime.request(command)
        self.trace.append({"command": command, "response": response})
        return response.get("result")

    def raw(self, command: dict[str, Any]) -> Any:
        return self._request(dict(command))

    def get_by_path(self, path: str) -> Locator:
        return Locator(self, path_selector(path))

    def get_by_model_id(self, model_id: str) -> Locator:
        return Locator(self, model_id_selector(model_id))

    def get_by_control_id(self, control_id: str) -> Locator:
        return Locator(self, control_id_selector(control_id))

    def locator(self, selector: Selector) -> Locator:
        return Locator(self, selector)

    def advance_frames(self, count: int) -> dict[str, Any]:
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise InputError("frame count must be a non-negative integer")
        result = self._request(Frames(count).to_command())
        return _mapping(result, "frames result")

    def resize_viewport(
        self, width: int, height: int, *, ui_scale: float | None = None
    ) -> dict[str, Any]:
        if (
            not isinstance(width, int)
            or isinstance(width, bool)
            or width <= 0
            or not isinstance(height, int)
            or isinstance(height, bool)
            or height <= 0
        ):
            raise InputError("viewport width and height must be positive integers")
        if ui_scale is not None and (
            not isinstance(ui_scale, (int, float))
            or isinstance(ui_scale, bool)
            or ui_scale <= 0
        ):
            raise InputError("viewport ui_scale must be positive")
        result = self._request(ResizeViewport(width, height, ui_scale).to_command())
        return _mapping(result, "resize viewport result")

    def resize_subject(self, width: int, height: int) -> dict[str, Any]:
        self._validate_positive_size(width, height, "subject")
        result = self._request(ResizeSubject(width, height).to_command())
        return _mapping(result, "resize subject result")

    def click_at(self, x: int, y: int) -> ActionResult:
        self._validate_coordinates((x, y))
        return self._perform_input(
            CoordinatePointerAction(PointerEvent.CLICK, MouseButton.LEFT, x, y),
            "click",
        )

    def double_click_at(self, x: int, y: int) -> ActionResult:
        self._validate_coordinates((x, y))
        return self._perform_input(
            CoordinatePointerAction(PointerEvent.DOUBLE_CLICK, MouseButton.LEFT, x, y),
            "doubleClick",
        )

    def right_click_at(self, x: int, y: int) -> ActionResult:
        self._validate_coordinates((x, y))
        return self._perform_input(
            CoordinatePointerAction(PointerEvent.CLICK, MouseButton.RIGHT, x, y),
            "rightClick",
        )

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int) -> ActionResult:
        self._validate_coordinates((start_x, start_y, end_x, end_y))
        return self._perform_input(DragAction(start_x, start_y, end_x, end_y), "drag")

    @staticmethod
    def _validate_positive_size(width: int, height: int, label: str) -> None:
        if (
            not isinstance(width, int)
            or isinstance(width, bool)
            or width <= 0
            or not isinstance(height, int)
            or isinstance(height, bool)
            or height <= 0
        ):
            raise InputError(f"{label} width and height must be positive integers")

    @staticmethod
    def _validate_coordinates(values: tuple[int, ...]) -> None:
        if any(
            not isinstance(value, int) or isinstance(value, bool) for value in values
        ):
            raise InputError("pointer coordinates must be integers")

    def _perform_input(self, operation: Any, action: str) -> ActionResult:
        self._require_capability("input")
        self._require_operation("XUILab", "input")
        self._require_input_operation(action)
        self.wait_for_stable()
        result = _mapping(self._request(operation.to_command()), f"{action} result")
        self.wait_for_stable()
        return ActionResult(action, result)

    def reload(self) -> dict[str, Any]:
        result = self._request(Reload().to_command())
        return _mapping(result, "reload result")

    def query_tree(self) -> dict[str, Any]:
        result = self._request(QueryTree().to_command())
        return _mapping(result, "tree result")

    def diagnostics(self) -> dict[str, Any]:
        result = self._request(Diagnostics().to_command())
        return _mapping(result, "diagnostics result")

    def capture(self, name: str, *, highlight: Locator | None = None) -> dict[str, Any]:
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or PureWindowsPath(name).drive
            or "/" in name
            or "\\" in name
        ):
            raise InputError("capture name must not create subdirectories")
        result = self._request(
            Capture(
                name=name,
                include_overlay=highlight is not None,
                highlight=highlight.selector if highlight is not None else None,
            ).to_command()
        )
        return _mapping(result, "capture result")

    def pick(self, x: int, y: int) -> Control:
        self._require_capability("inspection")
        result = _mapping(self._request(Pick(x, y).to_command()), "pick result")
        path = result.get("path")
        if not isinstance(path, str) or not path:
            raise AssertionFailure(f"no visible control at screen position ({x}, {y})")
        control_id = result.get("control_id")
        selector = (
            control_id_selector(control_id)
            if isinstance(control_id, str) and control_id
            else path_selector(path)
        )
        return Control(selector, result)

    def highlight(self, locator: Locator | None) -> dict[str, Any]:
        self._require_capability("inspection")
        result = self._request(
            Highlight(locator.selector if locator is not None else None).to_command()
        )
        return _mapping(result, "highlight result")

    def _require_capability(self, capability: str) -> None:
        if Capability(capability) not in self.capabilities:
            raise CapabilityError(f"window does not have the {capability!r} capability")

    def _require_operation(self, api: str, operation: str) -> None:
        metadata = self.event_apis.get(api)
        operations = metadata.get("operations") if isinstance(metadata, dict) else None
        names = (
            {entry.get("name") for entry in operations if isinstance(entry, dict)}
            if isinstance(operations, list)
            else set()
        )
        if operation not in names:
            raise CapabilityError(f"runtime does not expose {api}.{operation}")

    def _require_input_operation(self, operation: str) -> None:
        if operation not in self.input_operations:
            raise CapabilityError(
                f"runtime does not expose the input operation {operation!r}"
            )

    def wait_for_stable(self, stability: WaitForStable | None = None) -> dict[str, Any]:
        policy = stability or self.stability
        result = _mapping(self._request(policy.to_command()), "stable result")
        if result.get("stable") is True:
            return result
        first = self._request(QueryTree().to_command())
        self._request(Frames(1).to_command())
        second = self._request(QueryTree().to_command())
        first_state = _node_state(first)
        second_state = _node_state(second)
        changed = sorted(
            path
            for path in first_state.keys() | second_state.keys()
            if first_state.get(path) != second_state.get(path)
        )
        detail = (
            ", ".join(changed[:10])
            if changed
            else "no path-level differences were reported"
        )
        raise AssertionFailure(
            f"UI did not stabilize after {policy.maximum_frames} frames; changing paths: {detail}"
        )

    def expect_menu_visible(self, expected: bool = True) -> dict[str, Any]:
        self._require_capability("menus")
        self.wait_for_stable()
        result = _mapping(self._request(QueryMenus().to_command()), "menu query result")
        check_observation("menus", result, "/visible", Comparison.EQUALS, expected)
        return result

    def expect_recorded_effect(self, field: str, expected: Any) -> dict[str, Any]:
        self._require_capability("external_effects")
        self.wait_for_stable()
        result = _mapping(
            self._request(Diagnostics().to_command()), "diagnostics result"
        )
        effects = result.get("effects")
        matches = (
            [
                effect
                for effect in effects
                if isinstance(effect, dict) and effect.get(field) == expected
            ]
            if isinstance(effects, list)
            else []
        )
        if not matches:
            raise AssertionFailure(
                f"recorded effects do not contain {field}={expected!r}"
            )
        return matches[0]

    def _collect_failure(self, failure: BaseException) -> None:
        diagnostics: dict[str, Any] = {"passed": False, "error": str(failure)}
        for operation, filename, key in (
            (Capture(name="frame"), "frame.png", "capture"),
            (QueryTree(), "ui-tree.json", "tree"),
            (Diagnostics(), "diagnostics-runtime.json", "diagnostics"),
        ):
            try:
                result = self._request(operation.to_command())
                if filename.endswith(".json"):
                    write_json(self.artifact_dir / filename, result)
            except RuntimeFailure as artifact_error:
                diagnostics[f"{key}Error"] = str(artifact_error)
        write_json(self.artifact_dir / "diagnostics.json", diagnostics)

    def _finish(self, failure: BaseException | None) -> None:
        if self._finished:
            return
        if failure is not None:
            self._collect_failure(failure)
        close_failure: RuntimeFailure | None = None
        try:
            status = self.runtime.close()
            if status != 0 and failure is None:
                close_failure = RuntimeFailure(f"runtime exited with status {status}")
        except RuntimeFailure as error:
            if failure is None:
                close_failure = error
        write_json(self.artifact_dir / "event-trace.json", self.trace)
        if failure is None and close_failure is None:
            write_json(self.artifact_dir / "diagnostics.json", {"passed": True})
        elif failure is None and close_failure is not None:
            write_json(
                self.artifact_dir / "diagnostics.json",
                {"passed": False, "error": str(close_failure)},
            )
        self._finished = True
        if close_failure is not None:
            raise close_failure

    def close(self) -> None:
        self._finish(None)

    def __enter__(self) -> Window:
        return self

    def __exit__(
        self, _type: object, value: BaseException | None, _traceback: object
    ) -> None:
        self._finish(value)


class Locator:
    def __init__(self, window: Window, selector: Selector):
        self.window = window
        self.selector = selector

    def resolve(self) -> Control:
        tree = self.window._request(QueryTree().to_command())
        if isinstance(self.selector, PathSelector):
            matches = [
                node
                for node in _tree_nodes(tree)
                if node.get("path") == self.selector.path
            ]
        elif isinstance(self.selector, ControlIdSelector):
            matches = [
                node
                for node in _tree_nodes(tree)
                if node.get("control_id") == self.selector.control_id
            ]
        else:
            matches = [
                node
                for node in _tree_nodes(tree)
                if node.get("model_id") == self.selector.model_id
            ]
        if len(matches) != 1:
            descriptions = []
            for match in matches:
                path = match.get("path", "<unknown path>")
                runtime_class = match.get("class", "<unknown class>")
                source_file = match.get("source_file", "<unknown source>")
                source_line = match.get("source_line", 0)
                descriptions.append(
                    f"{path} ({runtime_class}, {source_file}:{source_line})"
                )
            detail = "; ".join(descriptions) if descriptions else "none"
            raise AssertionFailure(
                f"locator for {self.selector.describe()} resolved to {len(matches)} controls; matches: {detail}"
            )
        return Control(self.selector, matches[0])

    def _perform(self, event: PointerEvent, button: MouseButton) -> ActionResult:
        self.window._require_capability("input")
        self.window._require_operation("XUILab", "input")
        self.window._require_input_operation(event.value)
        self.window.wait_for_stable()
        self.resolve()
        operation = PointerAction(event, button, self.selector)
        result = _mapping(
            self.window._request(operation.to_command()), f"{event.value} result"
        )
        self.window.wait_for_stable()
        return ActionResult(event.value, result)

    def click(self) -> ActionResult:
        return self._perform(PointerEvent.CLICK, MouseButton.LEFT)

    def double_click(self) -> ActionResult:
        return self._perform(PointerEvent.DOUBLE_CLICK, MouseButton.LEFT)

    def right_click(self) -> ActionResult:
        return self._perform(PointerEvent.CLICK, MouseButton.RIGHT)

    def _unsupported(self, action: str) -> None:
        raise CapabilityError(f"runtime does not expose the locator action {action!r}")

    def fill(self, value: str) -> ActionResult:
        return self._perform_text(TextInput(value, self.selector, replace=True))

    def press(self, key: str, *, modifiers: tuple[str, ...] = ()) -> ActionResult:
        self.window._require_capability("input")
        self.window._require_operation("XUILab", "input")
        self.window._require_input_operation("key")
        self.window.wait_for_stable()
        self.resolve()
        operation = KeyInput(key, self.selector, modifiers)
        result = _mapping(self.window._request(operation.to_command()), "key result")
        self.window.wait_for_stable()
        return ActionResult("key", result)

    def type_text(self, value: str) -> ActionResult:
        return self._perform_text(TextInput(value, self.selector))

    def _perform_text(self, operation: TextInput) -> ActionResult:
        self.window._require_capability("input")
        self.window._require_operation("XUILab", "input")
        self.window._require_input_operation("fill" if operation.replace else "text")
        self.window.wait_for_stable()
        self.resolve()
        result = _mapping(self.window._request(operation.to_command()), "text result")
        self.window.wait_for_stable()
        return ActionResult("fill" if operation.replace else "text", result)

    def scroll(self, _clicks: int) -> None:
        self._unsupported("scroll")

    def drag_by(self, *, dx: int, dy: int) -> ActionResult:
        if any(
            not isinstance(value, int) or isinstance(value, bool) for value in (dx, dy)
        ):
            raise InputError("drag deltas must be integers")
        self.window._require_capability("input")
        self.window._require_operation("XUILab", "input")
        self.window._require_input_operation("drag")
        self.window.wait_for_stable()
        self.resolve()
        result = _mapping(
            self.window._request(
                DragAction(selector=self.selector, delta_x=dx, delta_y=dy).to_command()
            ),
            "drag result",
        )
        self.window.wait_for_stable()
        return ActionResult("drag", result)

    def drag_to(self, target: Locator) -> ActionResult:
        source_control = self.resolve()
        target_control = target.resolve()
        source_rect = source_control.info.get("screen_rect")
        target_rect = target_control.info.get("screen_rect")
        if not isinstance(source_rect, dict) or not isinstance(target_rect, dict):
            raise AssertionFailure("drag endpoints do not expose screen rectangles")

        def center(rect: dict[str, Any]) -> tuple[int, int]:
            values = tuple(rect.get(key) for key in ("left", "right", "bottom", "top"))
            if any(not isinstance(value, int) for value in values):
                raise AssertionFailure("drag endpoint has an invalid screen rectangle")
            left, right, bottom, top = values
            return ((left + right) // 2, (bottom + top) // 2)

        start_x, start_y = center(source_rect)
        end_x, end_y = center(target_rect)
        return self.window.drag(start_x, start_y, end_x, end_y)

    def expect(
        self, field: str, expected: Any, comparison: Comparison = Comparison.EQUALS
    ) -> Control:
        self.window.wait_for_stable()
        control = self.resolve()
        check_observation(
            self.selector.describe(), control.info, f"/{field}", comparison, expected
        )
        return control

    def expect_visible(self, expected: bool = True) -> Control:
        return self.expect("visible_chain", expected)

    def expect_enabled(self, expected: bool = True) -> Control:
        return self.expect("enabled_chain", expected)

    def expect_value(self, expected: Any) -> Control:
        return self.expect("value", expected)

    def expect_selected(self, expected: bool = True) -> Control:
        return self.expect("selected", expected)

    def expect_focused(self, expected: bool = True) -> Control:
        return self.expect("keyboard_focus", expected)

    def expect_local_rect(self, expected: dict[str, int]) -> Control:
        return self.expect("local_rect", expected)

    def expect_screen_rect(self, expected: dict[str, int]) -> Control:
        return self.expect("screen_rect", expected)

    def expect_clipping_rect(self, expected: dict[str, int]) -> Control:
        return self.expect("clipping_rect", expected)
