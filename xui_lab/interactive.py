"""Browser companion for a headed xui-lab runtime."""

from __future__ import annotations

import json
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from . import contracts
from .api import Lab, Locator, Window
from .domain import Capability, Viewport
from .errors import InputError, RuntimeFailure, XUILabError
from .inspector_assets import (
    INSPECTOR_ASSETS,
    inspector_assets_problem,
    inspector_build_instruction,
)
from .io import write_json
from .scenarios import Scenario

_ACTIONS_WITHOUT_AUTOMATIC_CAPTURE = frozenset(
    {"capture", "export", "highlight", "pick"}
)


def recorded_python(
    actions: list[dict[str, Any]], tree: dict[str, Any] | None = None
) -> list[str]:
    """Render runtime actions as editable public API calls."""
    from .selectors import rank_locator, tree_nodes

    nodes_by_id: dict[str, dict[str, Any]] = {}
    if tree is not None:
        for node in tree_nodes(tree):
            control_id = node.get("control_id")
            if isinstance(control_id, str) and control_id:
                nodes_by_id[control_id] = node
    lines: list[str] = []
    for action in actions:
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
            locator = rank_locator(nodes_by_id[control_id], tree).python
        elif isinstance(control_id, str) and control_id:
            locator = f"window.get_by_control_id({control_id!r})"
        elif isinstance(path, str):
            locator = f"window.get_by_path({path!r})"
        else:
            continue
        if kind in {"click", "double_click", "right_click"}:
            lines.append(f"{locator}.{kind}()")
        elif kind in {"fill", "text"} and isinstance(action.get("text"), str):
            method = "fill" if kind == "fill" else "type_text"
            lines.append(f"{locator}.{method}({action['text']!r})")
        elif kind == "key" and isinstance(action.get("key"), str):
            modifiers = action.get("modifiers")
            if (
                isinstance(modifiers, list)
                and modifiers
                and all(isinstance(modifier, str) for modifier in modifiers)
            ):
                lines.append(
                    f"{locator}.press({action['key']!r}, "
                    f"modifiers={tuple(modifiers)!r})"
                )
            else:
                lines.append(f"{locator}.press({action['key']!r})")
        elif (
            kind == "drag"
            and isinstance(action.get("deltaX"), int)
            and isinstance(action.get("deltaY"), int)
        ):
            lines.append(
                f"{locator}.drag_by(dx={action['deltaX']}, dy={action['deltaY']})"
            )
        elif kind == "scroll" and isinstance(action.get("clicks"), int):
            lines.append(f"{locator}.scroll({action['clicks']})")
        elif kind == "drag_and_drop":
            target_control_id = action.get("targetControlId")
            target_path = action.get("targetPath")
            if isinstance(target_control_id, str) and target_control_id:
                target = f"window.get_by_control_id({target_control_id!r})"
            elif isinstance(target_path, str) and target_path:
                target = f"window.get_by_path({target_path!r})"
            else:
                continue
            lines.append(f"{locator}.drag_to({target})")
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
            "artifactDir": str(self.window.artifact_dir),
            "subjects": sorted(self.subjects),
            "fixtures": sorted(self.fixtures),
            "scenarios": sorted(self.scenarios),
            "inputOperations": sorted(self.window.input_operations),
            "capture": {
                "available": self._latest_capture is not None,
                "version": self._capture_version,
            },
        }

    def action(self, request: dict[str, Any]) -> dict[str, Any]:
        action = contracts.parse_interactive_action({"schemaVersion": 1, **request})
        result = self._perform_action(action)
        if action.action not in _ACTIONS_WITHOUT_AUTOMATIC_CAPTURE:
            self._capture(action.action)
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
            source = self.window.get_by_control_id(request.source_control_id)
            target = self.window.get_by_control_id(request.target_control_id)
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

    def _capture(self, reason: str) -> dict[str, Any]:
        name = f"interactive-{self._capture_version + 1:04d}-{reason}"
        result = self.window.capture(name)
        self._latest_capture = self._capture_path(result)
        self._capture_version += 1
        return result

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
        if request.control_id is not None:
            return self.window.get_by_control_id(request.control_id)
        assert request.path is not None
        return self.window.get_by_path(request.path)

    def _optional_locator(
        self, request: contracts.HighlightInteractiveAction
    ) -> Locator | None:
        if request.control_id is not None:
            return self.window.get_by_control_id(request.control_id)
        if request.path is not None:
            return self.window.get_by_path(request.path)
        return None

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


ASSET_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}
MAX_ACTION_BYTES = 1024 * 1024


class InspectorSession(Protocol):
    @property
    def latest_capture(self) -> Path | None: ...

    def action(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def close(self) -> None: ...

    def state(self) -> dict[str, Any]: ...


class InspectorServer(ThreadingHTTPServer):
    session: InspectorSession
    assets = INSPECTOR_ASSETS
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
    ):
        self.session_lock = threading.Lock()
        super().__init__(server_address, handler)


class InspectorHandler(BaseHTTPRequestHandler):
    server: InspectorServer

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            self._asset("index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/assets/"):
            self._asset(path.removeprefix("/"))
            return
        if path == "/api/state":
            with self.server.session_lock:
                state = self.server.session.state()
            self._json(200, state)
            return
        if path == "/api/capture":
            with self.server.session_lock:
                capture = self.server.session.latest_capture
            if capture is None:
                self._json(404, {"error": "no screenshot has been captured"})
                return
            try:
                body = capture.read_bytes()
            except OSError:
                self._json(404, {"error": "the latest screenshot is unavailable"})
                return
            self._write(200, body, "image/png")
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/api/action":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > MAX_ACTION_BYTES:
                raise InputError(
                    f"request body must be between 1 and {MAX_ACTION_BYTES} bytes"
                )
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise InputError("request must be an object")
            with self.server.session_lock:
                result = self.server.session.action(value)
            self._json(200, {"ok": True, "result": result})
        except (ValueError, XUILabError) as error:
            record = contracts.error_record(error, operation="inspector.action")
            self._json(
                400,
                {
                    "ok": False,
                    "error": record.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    ),
                },
            )

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _json(self, status: int, value: Any) -> None:
        self._write(status, json.dumps(value).encode(), "application/json")

    def _asset(self, relative_path: str, content_type: str | None = None) -> None:
        root = self.server.assets.resolve()
        path = root.joinpath(relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            self._json(404, {"error": "not found"})
            return
        try:
            body = path.read_bytes()
        except OSError:
            self._json(404, {"error": "inspector asset is unavailable"})
            return
        resolved_content_type = content_type or ASSET_CONTENT_TYPES.get(
            path.suffix.lower(), "application/octet-stream"
        )
        self._write(200, body, resolved_content_type)

    def _write(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; connect-src 'self'",
        )
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def serve_inspector(
    session: InspectorSession,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
) -> int:
    assets_problem = inspector_assets_problem()
    if assets_problem is not None:
        raise RuntimeFailure(f"{assets_problem}; {inspector_build_instruction()}")
    server = InspectorServer((host, port), InspectorHandler)
    server.session = session
    bound_host = server.server_address[0]
    if isinstance(bound_host, bytes):
        bound_host = bound_host.decode()
    url = f"http://{bound_host}:{server.server_address[1]}/"
    print(f"xui-lab inspector: {url}", flush=True)
    if open_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        session.close()
    return 0
