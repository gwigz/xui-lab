"""Playwright-style control of one xui-lab runtime process."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from .assertions import check_observation
from .contracts import (
    SCHEMA_VERSION,
    ArtifactEntry,
    ArtifactKind,
    ArtifactManifest,
    RuntimeExchangeEvent,
    Selector,
    error_record,
    parse_capture_metadata,
    parse_fixture,
)
from .contracts import (
    ControlIdSelectorContract as ControlIdSelector,
)
from .contracts import (
    ModelIdSelectorContract as ModelIdSelector,
)
from .contracts import (
    PathSelectorContract as PathSelector,
)
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
    CoordinatePointerAction,
    CoordinateScrollAction,
    Diagnostics,
    DragAction,
    DragAndDropAction,
    Frames,
    Highlight,
    KeyInput,
    MouseButton,
    Pick,
    PointerAction,
    PointerEvent,
    QueryMenus,
    QueryTree,
    Reload,
    ResizeSubject,
    ResizeViewport,
    ScrollAction,
    TextInput,
    WaitForStable,
    control_id_selector,
    label_selector,
    model_id_selector,
    path_selector,
    placeholder_selector,
    role_selector,
    text_selector,
)
from .protocol import RuntimeProcess
from .selectors import excerpt_node, require_unique, wire_selector


@dataclass(frozen=True)
class _CaptureRecord:
    path: Path
    action: str | None
    selector: Selector | None
    sequence: int


ENV_ARTIFACTS_DIR = "XUI_LAB_ARTIFACTS_DIR"


def default_artifact_root() -> Path:
    """Return the artifact root used when a command omits --artifacts."""
    override = os.environ.get(ENV_ARTIFACTS_DIR)
    if override:
        return Path(override).expanduser().resolve()
    return Path(tempfile.gettempdir()) / f"xui-lab-{os.getuid()}" / "artifacts"


def artifact_directory(root: Path, artifact_id: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / artifact_id).resolve()
    if candidate.parent != resolved_root:
        raise InputError(f"artifact directory escapes artifact root: {artifact_id}")
    return candidate


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


@dataclass(frozen=True)
class MenuEntry:
    """One visible production menu entry from a menus query."""

    label: str
    menu: str
    path: str
    control_id: str
    enabled: bool
    separator: bool
    source_file: str
    source_line: int

    @property
    def selector(self) -> Selector:
        if self.control_id:
            return control_id_selector(self.control_id)
        return path_selector(self.path)

    def describe(self) -> str:
        state = "enabled" if self.enabled else "disabled"
        return f"{self.label!r} ({state}, {self.source_file}:{self.source_line})"


def _source_line(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _menu_entries(result: dict[str, Any]) -> tuple[MenuEntry, ...]:
    entries = result.get("entries")
    if not isinstance(entries, list):
        raise AssertionFailure("menus query returned no entries list")
    return tuple(
        MenuEntry(
            label=str(entry.get("label", "")),
            menu=str(entry.get("menu", "")),
            path=str(entry.get("path", "")),
            control_id=str(entry.get("control_id", "")),
            enabled=entry.get("enabled") is True,
            separator=entry.get("separator") is True,
            source_file=str(entry.get("source_file", "")),
            source_line=_source_line(entry.get("source_line")),
        )
        for entry in entries
        if isinstance(entry, dict)
    )


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
        request_id: str | None = None,
        request_timeout: float = 10.0,
        shutdown_timeout: float = 10.0,
    ) -> Window:
        fixture_data = None
        if fixture is not None:
            fixture_contract = parse_fixture(read_json(fixture))
            fixture_data = fixture_contract.model_dump(
                mode="json", by_alias=True, exclude_none=True
            )
        fork_commit = git_commit(self.viewer_source)
        artifact_dir = artifact_directory(self.artifact_root, artifact_id)
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True)
        runtime = RuntimeProcess(
            self.executable,
            artifact_dir / "runtime.log",
            mode="interactive" if interactive else "scenario",
            request_timeout=request_timeout,
            shutdown_timeout=shutdown_timeout,
        )
        window = Window(
            runtime,
            artifact_dir,
            stability,
            artifact_id=artifact_id,
            fork=str(self.fork.id),
            fork_commit=fork_commit,
            subject=subject,
            fixture=fixture_contract.id if fixture is not None else None,
            request_id=request_id,
        )
        try:
            initialize = {
                "op": "initialize",
                "fork": self.fork.id,
                "forkCommit": fork_commit,
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
            supported = hello["supportedCapabilities"]
            missing = sorted(str(value) for value in capabilities - set(supported))
            if missing:
                raise CapabilityError(
                    f"runtime is missing capabilities: {', '.join(missing)}"
                )

            installed = window._request(
                {"op": "installCapabilities", "capabilities": sorted(capabilities)}
            )
            installed_capabilities = installed["capabilities"]
            event_apis = installed["eventApis"]
            input_operations = installed["inputOperations"]
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
        self,
        runtime: RuntimeProcess,
        artifact_dir: Path,
        stability: WaitForStable,
        *,
        artifact_id: str,
        fork: str,
        fork_commit: str,
        subject: str,
        fixture: str | None,
        request_id: str | None = None,
    ):
        self.runtime = runtime
        self.artifact_dir = artifact_dir
        self.stability = stability
        self.trace: list[dict[str, Any]] = []
        self.capabilities: frozenset[Capability] = frozenset()
        self.event_apis: dict[str, Any] = {}
        self.input_operations: frozenset[str] = frozenset()
        self._artifact_id = artifact_id
        self._fork = fork
        self._fork_commit = fork_commit
        self._subject = subject
        self._fixture = fixture
        self._request_id = request_id
        self._finished = False
        self._capture_sequence = 0
        self._capture_records: list[_CaptureRecord] = []

    @property
    def subject(self) -> str:
        return self._subject

    @property
    def fixture(self) -> str | None:
        return self._fixture

    def _install(
        self,
        capabilities: frozenset[Capability],
        event_apis: dict[str, Any],
        input_operations: frozenset[str],
    ) -> None:
        self.capabilities = capabilities
        self.event_apis = event_apis
        self.input_operations = input_operations

    def _request(self, command: dict[str, Any]) -> dict[str, Any]:
        response = self.runtime.request(command)
        event = RuntimeExchangeEvent(
            schemaVersion=SCHEMA_VERSION,
            type="event",
            event="runtimeExchange",
            sequence=len(self.trace),
            operation=str(command.get("op", "unknown")),
            command={"schemaVersion": SCHEMA_VERSION, **command},
            response=response,
        )
        self.trace.append(
            event.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        result = response["result"]
        assert isinstance(result, dict)
        return result

    def raw(self, command: dict[str, Any]) -> Any:
        return self._request(dict(command))

    def get_by_path(self, path: str) -> Locator:
        return Locator(self, path_selector(path))

    def get_by_model_id(self, model_id: str) -> Locator:
        return Locator(self, model_id_selector(model_id))

    def get_by_control_id(self, control_id: str) -> Locator:
        return Locator(self, control_id_selector(control_id))

    def get_by_role(self, role: str, *, name: str | None = None) -> Locator:
        return Locator(self, role_selector(role, name))

    def get_by_label(self, label: str) -> Locator:
        return Locator(self, label_selector(label))

    def get_by_placeholder(self, placeholder: str) -> Locator:
        return Locator(self, placeholder_selector(placeholder))

    def get_by_text(self, text: str) -> Locator:
        return Locator(self, text_selector(text))

    def locator(self, selector: Selector) -> Locator:
        return Locator(self, selector)

    def advance_frames(self, count: int) -> dict[str, Any]:
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise InputError("frame count must be a non-negative integer")
        return self._request(Frames(count).to_command())

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
        return self._request(ResizeViewport(width, height, ui_scale).to_command())

    def resize_subject(self, width: int, height: int) -> dict[str, Any]:
        self._validate_positive_size(width, height, "subject")
        return self._request(ResizeSubject(width, height).to_command())

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

    def scroll_at(self, x: int, y: int, clicks: int) -> ActionResult:
        self._validate_coordinates((x, y))
        self._validate_scroll_clicks(clicks)
        return self._perform_input(
            CoordinateScrollAction(x=x, y=y, clicks=clicks), "scroll"
        )

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

    @staticmethod
    def _validate_scroll_clicks(clicks: int) -> None:
        if not isinstance(clicks, int) or isinstance(clicks, bool) or clicks == 0:
            raise InputError("scroll clicks must be a non-zero integer")

    def _perform_input(self, operation: Any, action: str) -> ActionResult:
        self._require_capability("input")
        self._require_operation("XUILab", "input")
        self._require_input_operation(action)
        self.wait_for_stable()
        result = self._request(operation.to_command())
        self.wait_for_stable()
        return ActionResult(action, result)

    def reload(self) -> dict[str, Any]:
        return self._request(Reload().to_command())

    def query_tree(self) -> dict[str, Any]:
        return self._request(QueryTree().to_command())

    def diagnostics(self) -> dict[str, Any]:
        return self._request(Diagnostics().to_command())

    def capture(
        self,
        name: str,
        *,
        highlight: Locator | None = None,
        step: str | None = None,
        action: str | None = None,
        selector: Selector | None = None,
    ) -> dict[str, Any]:
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or PureWindowsPath(name).drive
            or "/" in name
            or "\\" in name
        ):
            raise InputError("capture name must not create subdirectories")
        self._capture_sequence += 1
        sequence = self._capture_sequence
        capture_step = step or name
        capture_action = action or name
        capture_selector = (
            selector
            if selector is not None
            else highlight.selector
            if highlight
            else None
        )
        result = self._request(
            Capture(
                name=name,
                include_overlay=highlight is not None,
                highlight=highlight.selector if highlight is not None else None,
                step=capture_step,
                sequence=sequence,
                action=capture_action,
            ).to_command()
        )
        return self._record_capture(
            result,
            action=capture_action,
            selector=capture_selector,
            sequence=sequence,
            step=capture_step,
        )

    def pick(self, x: int, y: int) -> Control:
        self._require_capability("inspection")
        result = self._request(Pick(x, y).to_command())
        path = result.get("path")
        if not isinstance(path, str) or not path:
            tree = self.query_tree()
            raise AssertionFailure(
                f"no visible control at screen position ({x}, {y})",
                tree_excerpt=excerpt_node(tree, children=True)
                if isinstance(tree, dict)
                else None,
            )
        control_id = result.get("control_id")
        selector = (
            control_id_selector(control_id)
            if isinstance(control_id, str) and control_id
            else path_selector(path)
        )
        return Control(selector, result)

    def highlight(self, locator: Locator | None) -> dict[str, Any]:
        self._require_capability("inspection")
        return self._request(
            Highlight(locator.selector if locator is not None else None).to_command()
        )

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
        result = self._request(policy.to_command())
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
        result = self._request(QueryMenus().to_command())
        check_observation("menus", result, "/visible", Comparison.EQUALS, expected)
        return result

    def menu_entries(self) -> tuple[MenuEntry, ...]:
        self._require_capability("menus")
        self.wait_for_stable()
        return _menu_entries(self._request(QueryMenus().to_command()))

    def expect_menu_entry(
        self, label: str, *, enabled: bool | None = None
    ) -> MenuEntry:
        entries = self.menu_entries()
        matches = [entry for entry in entries if entry.label == label]
        if len(matches) != 1:
            available = ", ".join(
                entry.describe() for entry in entries if not entry.separator
            )
            raise AssertionFailure(
                f"menu entry {label!r} matched {len(matches)} entries; "
                f"visible entries: {available or 'none'}"
            )
        entry = matches[0]
        if enabled is not None and entry.enabled is not enabled:
            raise AssertionFailure(
                f"menu entry {label!r} is "
                f"{'enabled' if entry.enabled else 'disabled'}, expected "
                f"{'enabled' if enabled else 'disabled'} "
                f"({entry.source_file}:{entry.source_line})"
            )
        return entry

    def expect_recorded_effect(self, field: str, expected: Any) -> dict[str, Any]:
        self._require_capability("external_effects")
        self.wait_for_stable()
        result = self._request(Diagnostics().to_command())
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

    def expect_no_recorded_effect(self, field: str, unexpected: Any) -> None:
        self._require_capability("external_effects")
        self.wait_for_stable()
        result = self._request(Diagnostics().to_command())
        effects = result.get("effects")
        matches = (
            [
                effect
                for effect in effects
                if isinstance(effect, dict) and effect.get(field) == unexpected
            ]
            if isinstance(effects, list)
            else []
        )
        if matches:
            raise AssertionFailure(
                f"recorded effects unexpectedly contain {field}={unexpected!r}"
            )

    def _collect_failure(self, failure: BaseException) -> None:
        diagnostics: dict[str, Any] = {"passed": False, "error": str(failure)}
        write_json(
            self.artifact_dir / "error.json",
            error_record(failure, operation="scenario").model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
        )
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
            write_json(
                self.artifact_dir / "error.json",
                error_record(close_failure, operation="shutdown").model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
            )
        self._write_artifact_manifest()
        self._finished = True
        if close_failure is not None:
            raise close_failure

    def close(self) -> None:
        self._finish(None)

    def _record_capture(
        self,
        result: dict[str, Any],
        *,
        action: str,
        selector: Selector | None,
        sequence: int,
        step: str,
    ) -> dict[str, Any]:
        raw_path = result.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            return result
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.artifact_dir / path
        resolved = path.resolve()
        try:
            resolved.relative_to(self.artifact_dir.resolve())
        except ValueError:
            return result
        metadata = result.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            sidecar = Path(str(resolved) + ".json")
            if sidecar.is_file():
                loaded = read_json(sidecar)
                if isinstance(loaded, dict):
                    metadata = loaded
        metadata["scenarioStep"] = step
        metadata["action"] = action
        metadata["sequence"] = sequence
        if selector is not None:
            metadata["selector"] = selector.model_dump(mode="json", by_alias=True)
        metadata = parse_capture_metadata(metadata).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        sidecar_path = Path(str(resolved) + ".json")
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(sidecar_path, metadata)
        self._capture_records.append(
            _CaptureRecord(
                path=resolved,
                action=action,
                selector=selector,
                sequence=sequence,
            )
        )
        return {**result, "metadata": metadata}

    @staticmethod
    def _artifact_kind(path: Path) -> ArtifactKind:
        if path.suffix == ".png":
            return "frame"
        if path.name.endswith(".png.json"):
            return "captureMetadata"
        kinds: dict[str, ArtifactKind] = {
            "ui-tree.json": "tree",
            "ui-tree-export.json": "tree",
            "event-trace.json": "eventTrace",
            "diagnostics.json": "diagnostics",
            "diagnostics-runtime.json": "diagnostics",
            "error.json": "error",
            "runtime.log": "runtimeLog",
        }
        return kinds.get(path.name, "other")

    def _write_artifact_manifest(self) -> None:
        entries = []
        for path in sorted(self.artifact_dir.rglob("*")):
            if not path.is_file() or path.name == "artifact-manifest.json":
                continue
            data = path.read_bytes()
            kind = self._artifact_kind(path)
            record = next(
                (item for item in self._capture_records if item.path == path.resolve()),
                None,
            )
            entries.append(
                ArtifactEntry(
                    kind=kind,
                    path=str(path.resolve()),
                    size=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    action=record.action
                    if record is not None and kind == "frame"
                    else None,
                    selector=record.selector
                    if record is not None and kind == "frame"
                    else None,
                    sequence=record.sequence
                    if record is not None and kind == "frame"
                    else None,
                )
            )
        manifest = ArtifactManifest(
            schemaVersion=SCHEMA_VERSION,
            artifactId=self._artifact_id,
            fork=self._fork,
            forkCommit=self._fork_commit,
            subject=self._subject,
            fixture=self._fixture,
            requestId=self._request_id,
            artifacts=tuple(entries),
        )
        write_json(
            self.artifact_dir / "artifact-manifest.json",
            manifest.model_dump(mode="json", by_alias=True, exclude_none=True),
        )

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
        node = require_unique(tree, self.selector)
        return Control(self.selector, node)

    def _input_selector(self) -> Selector:
        if isinstance(
            self.selector, (PathSelector, ControlIdSelector, ModelIdSelector)
        ):
            self.resolve()
            return self.selector
        return wire_selector(self.resolve().info)

    def _perform(self, event: PointerEvent, button: MouseButton) -> ActionResult:
        self.window._require_capability("input")
        self.window._require_operation("XUILab", "input")
        self.window._require_input_operation(event.value)
        self.window.wait_for_stable()
        operation = PointerAction(event, button, self._input_selector())
        result = self.window._request(operation.to_command())
        self.window.wait_for_stable()
        return ActionResult(event.value, result)

    def click(self) -> ActionResult:
        return self._perform(PointerEvent.CLICK, MouseButton.LEFT)

    def double_click(self) -> ActionResult:
        return self._perform(PointerEvent.DOUBLE_CLICK, MouseButton.LEFT)

    def right_click(self) -> ActionResult:
        return self._perform(PointerEvent.CLICK, MouseButton.RIGHT)

    def fill(self, value: str) -> ActionResult:
        return self._perform_text(TextInput(value, self.selector, replace=True))

    def press(self, key: str, *, modifiers: tuple[str, ...] = ()) -> ActionResult:
        self.window._require_capability("input")
        self.window._require_operation("XUILab", "input")
        self.window._require_input_operation("key")
        self.window.wait_for_stable()
        operation = KeyInput(key, self._input_selector(), modifiers)
        result = self.window._request(operation.to_command())
        self.window.wait_for_stable()
        return ActionResult("key", result)

    def type_text(self, value: str) -> ActionResult:
        return self._perform_text(TextInput(value, self.selector))

    def _perform_text(self, operation: TextInput) -> ActionResult:
        self.window._require_capability("input")
        self.window._require_operation("XUILab", "input")
        self.window._require_input_operation("fill" if operation.replace else "text")
        self.window.wait_for_stable()
        wired = TextInput(operation.text, self._input_selector(), operation.replace)
        result = self.window._request(wired.to_command())
        self.window.wait_for_stable()
        return ActionResult("fill" if operation.replace else "text", result)

    def scroll(self, clicks: int) -> ActionResult:
        self.window._validate_scroll_clicks(clicks)
        self.window._require_capability("input")
        self.window._require_operation("XUILab", "input")
        self.window._require_input_operation("scroll")
        self.window.wait_for_stable()
        result = self.window._request(
            ScrollAction(clicks, self._input_selector()).to_command()
        )
        self.window.wait_for_stable()
        return ActionResult("scroll", result)

    def drag_by(self, *, dx: int, dy: int) -> ActionResult:
        if any(
            not isinstance(value, int) or isinstance(value, bool) for value in (dx, dy)
        ):
            raise InputError("drag deltas must be integers")
        self.window._require_capability("input")
        self.window._require_operation("XUILab", "input")
        self.window._require_input_operation("drag")
        self.window.wait_for_stable()
        result = self.window._request(
            DragAction(
                selector=self._input_selector(), delta_x=dx, delta_y=dy
            ).to_command()
        )
        self.window.wait_for_stable()
        return ActionResult("drag", result)

    def drag_to(self, target: Locator) -> ActionResult:
        if target.window is not self.window:
            raise InputError("drag-and-drop locators must belong to the same window")
        self.window._require_capability("input")
        self.window._require_operation("XUILab", "input")
        self.window._require_input_operation("dragAndDrop")
        self.window.wait_for_stable()
        target_selector = (
            target.selector
            if isinstance(target.selector, (PathSelector, ControlIdSelector))
            else target._input_selector()
        )
        result = self.window._request(
            DragAndDropAction(self._input_selector(), target_selector).to_command()
        )
        self.window.wait_for_stable()
        return ActionResult("dragAndDrop", result)

    def expect(
        self, field: str, expected: Any, comparison: Comparison = Comparison.EQUALS
    ) -> Control:
        self.window.wait_for_stable()
        control = self.resolve()
        try:
            check_observation(
                self.selector.describe(),
                control.info,
                f"/{field}",
                comparison,
                expected,
            )
        except AssertionFailure as error:
            if error.tree_excerpt is None:
                error.tree_excerpt = excerpt_node(control.info, children=True)
            if error.selector is None:
                error.selector = self.selector
            raise
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
