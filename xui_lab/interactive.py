"""Browser companion for a headed xui-lab runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from . import contracts
from .api import Lab, Locator, Window
from .contracts import Selector, SelectorContract
from .domain import Capability, Viewport
from .errors import InputError, RuntimeFailure
from .io import read_json, write_json
from .scenarios import Scenario
from .selectors import rank_locator, ranked_locator_record, tree_nodes

_ACTIONS_WITHOUT_AUTOMATIC_CAPTURE = frozenset(
    {"capture", "export", "highlight", "pick"}
)


def _selector(value: object) -> Selector | None:
    if value is None:
        return None
    try:
        payload = (
            value.model_dump(mode="json", by_alias=True)
            if hasattr(value, "model_dump")
            else value
        )
        return SelectorContract.validate_python(payload)
    except (TypeError, ValueError, AttributeError, ValidationError):
        return None


def recorded_python(
    actions: list[dict[str, Any]], tree: dict[str, Any] | None = None
) -> list[str]:
    """Render runtime actions as editable public API calls."""
    from .selectors import explain_ranked_locator, rank_locator, tree_nodes

    nodes_by_id: dict[str, dict[str, Any]] = {}
    if tree is not None:
        for node in tree_nodes(tree):
            control_id = node.get("control_id")
            if isinstance(control_id, str) and control_id:
                nodes_by_id[control_id] = node
    lines: list[str] = []
    for action in actions:
        ranked = None
        target_ranked = None
        path = action.get("path")
        control_id = action.get("controlId")
        kind = action.get("action")
        if not isinstance(kind, str):
            continue
        if (
            tree is not None
            and isinstance(control_id, str)
            and control_id in nodes_by_id
        ):
            ranked = rank_locator(nodes_by_id[control_id], tree)
            locator = ranked.python
        elif isinstance(control_id, str) and control_id:
            locator = f"window.get_by_control_id({control_id!r})"
        elif isinstance(path, str):
            locator = f"window.get_by_path({path!r})"
        else:
            continue
        if kind in {"click", "double_click", "right_click"}:
            statement = f"{locator}.{kind}()"
        elif kind in {"fill", "text"} and isinstance(action.get("text"), str):
            method = "fill" if kind == "fill" else "type_text"
            statement = f"{locator}.{method}({action['text']!r})"
        elif kind == "key" and isinstance(action.get("key"), str):
            modifiers = action.get("modifiers")
            if (
                isinstance(modifiers, list)
                and modifiers
                and all(isinstance(modifier, str) for modifier in modifiers)
            ):
                statement = (
                    f"{locator}.press({action['key']!r}, "
                    f"modifiers={tuple(modifiers)!r})"
                )
            else:
                statement = f"{locator}.press({action['key']!r})"
        elif (
            kind == "drag"
            and isinstance(action.get("deltaX"), int)
            and isinstance(action.get("deltaY"), int)
        ):
            statement = (
                f"{locator}.drag_by(dx={action['deltaX']}, dy={action['deltaY']})"
            )
        elif kind == "scroll" and isinstance(action.get("clicks"), int):
            statement = f"{locator}.scroll({action['clicks']})"
        elif kind == "drag_and_drop":
            target_control_id = action.get("targetControlId")
            target_path = action.get("targetPath")
            if (
                tree is not None
                and isinstance(target_control_id, str)
                and target_control_id in nodes_by_id
            ):
                target_ranked = rank_locator(nodes_by_id[target_control_id], tree)
                target = target_ranked.python
            elif isinstance(target_control_id, str) and target_control_id:
                target = f"window.get_by_control_id({target_control_id!r})"
            elif isinstance(target_path, str) and target_path:
                target = f"window.get_by_path({target_path!r})"
            else:
                continue
            statement = f"{locator}.drag_to({target})"
        else:
            continue
        if ranked is not None:
            lines.append(explain_ranked_locator(ranked))
        if target_ranked is not None:
            lines.append(
                explain_ranked_locator(target_ranked, subject="target locator")
            )
        lines.append(statement)
    return lines


@dataclass(frozen=True)
class InteractiveConfig:
    subject: str
    viewport: Viewport
    fixture: Path | None
    artifact_id: str
    request_id: str | None = None


class InteractiveSession:
    def __init__(
        self,
        lab: Lab,
        config: InteractiveConfig,
        subjects: dict[str, frozenset[Capability]],
        fixtures: dict[str, Path],
        scenarios: dict[str, Scenario],
    ):
        self.lab = lab
        self.config = config
        self.subjects = subjects
        self.fixtures = fixtures
        self.scenarios = scenarios
        self._generation = 0
        self._latest_capture: Path | None = None
        self._capture_version = 0
        self._captures: dict[int, Path] = {}
        self._filmstrip: list[dict[str, Any]] = []
        self.window = self._open(config.subject, config.fixture)
        try:
            self._capture("initial")
        except Exception:
            self.window.close()
            raise

    def _open(self, subject: str, fixture: Path | None) -> Window:
        capabilities = self.subjects.get(subject)
        if capabilities is None:
            raise InputError(f"interactive subject is not declared: {subject}")
        artifact_id = self.config.artifact_id
        if self._generation:
            artifact_id = f"{artifact_id}-{self._generation}"
        self._generation += 1
        return self.lab.open(
            artifact_id=artifact_id,
            subject=subject,
            viewport=self.config.viewport,
            capabilities=capabilities,
            fixture=fixture,
            interactive=True,
            request_id=self.config.request_id,
        )

    def close(self) -> None:
        self.window.close()

    def artifact_directory(self) -> Path:
        return self.window.artifact_dir

    def state(self) -> dict[str, Any]:
        tree = self.window.query_tree()
        diagnostics = self.window.diagnostics()
        actions = (
            diagnostics.get("recording", []) if isinstance(diagnostics, dict) else []
        )
        return {
            "tree": tree,
            "diagnostics": diagnostics,
            "recording": recorded_python(
                actions if isinstance(actions, list) else [], tree
            ),
            "locators": {
                control_id: ranked_locator_record(rank_locator(node, tree))
                for node in tree_nodes(tree)
                if isinstance((control_id := node.get("control_id")), str)
                and control_id
            },
            "artifactDir": str(self.window.artifact_dir),
            "subjects": sorted(self.subjects),
            "fixtures": sorted(self.fixtures),
            "scenarios": sorted(self.scenarios),
            "inputOperations": sorted(self.window.input_operations),
            "capture": {
                "available": self._latest_capture is not None,
                "version": self._capture_version,
            },
            "captures": list(getattr(self, "_filmstrip", [])),
        }

    def action(self, request: dict[str, Any]) -> dict[str, Any]:
        action = contracts.parse_interactive_action({"schemaVersion": 1, **request})
        result = self._perform_action(action)
        if action.action not in _ACTIONS_WITHOUT_AUTOMATIC_CAPTURE:
            self._capture(action.action, selector=getattr(action, "selector", None))
        return result

    def _perform_action(self, request: contracts.InteractiveAction) -> dict[str, Any]:
        if isinstance(request, contracts.SimpleInteractiveAction):
            if request.action == "capture":
                return self._capture("manual")
            if request.action == "export":
                tree = self.window.query_tree()
                path = self.window.artifact_dir / "ui-tree-export.json"
                write_json(path, tree)
                return {"path": str(path)}
            before = self.window.runtime.pid
            result = self.window.reload()
            return {
                "result": result,
                "processIdBefore": before,
                "processIdAfter": self.window.runtime.pid,
            }
        if isinstance(request, contracts.HighlightInteractiveAction):
            locator = self._optional_locator(request)
            return self.window.highlight(locator)
        if isinstance(request, contracts.PickInteractiveAction):
            control = self.window.pick(request.x, request.y)
            self.window.highlight(self.window.locator(control.selector))
            return control.info
        if isinstance(request, contracts.ResizeViewportInteractiveAction):
            return self.window.resize_viewport(
                request.width, request.height, ui_scale=request.ui_scale
            )
        if isinstance(request, contracts.ResizeSubjectInteractiveAction):
            return self.window.resize_subject(request.width, request.height)
        if isinstance(request, contracts.LocatorInteractiveAction):
            return self._locator(request).click().data
        if isinstance(request, contracts.CoordinateInteractiveAction):
            if request.action == "doubleClickAt":
                return self.window.double_click_at(request.x, request.y).data
            if request.action == "rightClickAt":
                return self.window.right_click_at(request.x, request.y).data
            return self.window.click_at(request.x, request.y).data
        if isinstance(request, contracts.DragInteractiveAction):
            return self.window.drag(
                request.start_x, request.start_y, request.end_x, request.end_y
            ).data
        if isinstance(request, contracts.ScrollInteractiveAction):
            return self.window.scroll_at(request.x, request.y, request.clicks).data
        if isinstance(request, contracts.DragAndDropInteractiveAction):
            source = self.window.locator(request.source)
            target = self.window.locator(request.target)
            return source.drag_to(target).data
        if isinstance(request, contracts.TextInteractiveAction):
            locator = self._locator(request)
            return (
                locator.fill(request.text).data
                if request.action == "fill"
                else locator.type_text(request.text).data
            )
        if isinstance(request, contracts.PressInteractiveAction):
            return (
                self._locator(request)
                .press(request.key, modifiers=request.modifiers)
                .data
            )
        if isinstance(request, contracts.ReplayInteractiveAction):
            scenario = self.scenarios.get(request.scenario)
            if scenario is None:
                raise InputError(f"unknown scenario: {request.scenario}")
            return self._replay(scenario)
        if isinstance(request, contracts.SwitchInteractiveAction):
            fixture = self.fixtures.get(request.fixture) if request.fixture else None
            self.window.close()
            self.window = self._open(request.subject, fixture)
            self._latest_capture = None
            return {
                "subject": request.subject,
                "fixture": request.fixture or "",
                "processId": self.window.runtime.pid,
            }
        raise AssertionError("unhandled validated interactive action")

    @property
    def latest_capture(self) -> Path | None:
        return self._latest_capture

    def capture_path(self, version: int) -> Path | None:
        captures = getattr(self, "_captures", None)
        if not isinstance(captures, dict):
            return None
        path = captures.get(version)
        return path if isinstance(path, Path) else None

    def capture_snapshot(self, version: int) -> dict[str, Any] | None:
        path = self.capture_path(version)
        if path is None:
            return None
        snapshot_path = path.with_name(f"{path.stem}.snapshot.json")
        if not snapshot_path.is_file():
            return None
        payload = read_json(snapshot_path)
        return payload if isinstance(payload, dict) else None

    def _capture(self, reason: str, selector: object | None = None) -> dict[str, Any]:
        name = f"interactive-{self._capture_version + 1:04d}-{reason}"
        capture_selector = _selector(selector)
        try:
            result = self.window.capture(
                name, action=reason, selector=capture_selector, step=reason
            )
        except TypeError:
            result = self.window.capture(name)
        path = self._capture_path(result)
        self._latest_capture = path
        self._capture_version += 1
        captures = getattr(self, "_captures", None)
        if captures is None:
            self._captures = {}
            captures = self._captures
        captures[self._capture_version] = path
        filmstrip = getattr(self, "_filmstrip", None)
        if filmstrip is None:
            self._filmstrip = []
            filmstrip = self._filmstrip
        entry = {
            "version": self._capture_version,
            "sequence": self._capture_version,
            "action": reason,
            "name": name,
            "selector": (
                capture_selector.model_dump(mode="json", by_alias=True)
                if capture_selector is not None
                else None
            ),
        }
        filmstrip.append(entry)
        self._write_capture_snapshot(path, entry)
        return result

    def _write_capture_snapshot(self, path: Path, entry: dict[str, Any]) -> None:
        query_tree = getattr(self.window, "query_tree", None)
        diagnostics_fn = getattr(self.window, "diagnostics", None)
        if not callable(query_tree) or not callable(diagnostics_fn):
            return
        tree = query_tree()
        diagnostics = diagnostics_fn()
        actions = (
            diagnostics.get("recording", []) if isinstance(diagnostics, dict) else []
        )
        recording = recorded_python(actions if isinstance(actions, list) else [], tree)
        locators = {
            control_id: ranked_locator_record(rank_locator(node, tree))
            for node in tree_nodes(tree)
            if isinstance((control_id := node.get("control_id")), str) and control_id
        }
        write_json(
            path.with_name(f"{path.stem}.snapshot.json"),
            {
                "schemaVersion": 1,
                "version": entry["version"],
                "sequence": entry["sequence"],
                "action": entry["action"],
                "name": entry["name"],
                "selector": entry["selector"],
                "tree": tree,
                "diagnostics": diagnostics,
                "recording": recording,
                "locators": locators,
            },
        )

    def _capture_path(self, result: dict[str, Any]) -> Path:
        value = result.get("path")
        if not isinstance(value, str):
            raise RuntimeFailure("capture result path must be a string")
        path = Path(value).resolve()
        artifact_dir = self.window.artifact_dir.resolve()
        try:
            path.relative_to(artifact_dir)
        except ValueError as error:
            raise RuntimeFailure(
                f"capture path is outside the artifact directory: {path}"
            ) from error
        if path.suffix.lower() != ".png" or not path.is_file():
            raise RuntimeFailure(f"capture result is not a PNG file: {path}")
        return path

    def _locator(self, request: contracts.TargetedInteractiveAction) -> Locator:
        return self.window.locator(request.selector)

    def _optional_locator(
        self, request: contracts.HighlightInteractiveAction
    ) -> Locator | None:
        return (
            self.window.locator(request.selector)
            if request.selector is not None
            else None
        )

    def _replay(self, scenario: Scenario) -> dict[str, Any]:
        diagnostics = self.window.diagnostics()
        subject = (
            diagnostics.get("subject", {}).get("id")
            if isinstance(diagnostics, dict)
            else None
        )
        if subject != scenario.subject:
            raise InputError(
                f"scenario {scenario.id} targets {scenario.subject}, headed subject is {subject}"
            )
        before = self.window.runtime.pid
        self.window.reload()
        scenario.run(self.window)
        return {
            "scenario": str(scenario.id),
            "passed": True,
            "processIdBefore": before,
            "processIdAfter": self.window.runtime.pid,
        }


def discover_fixtures(root: Path) -> dict[str, Path]:
    return {path.stem: path for path in sorted((root / "fixtures").glob("*.json"))}
