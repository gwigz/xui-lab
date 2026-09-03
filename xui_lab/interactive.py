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
_KEY_MODIFIERS = frozenset({"shift", "control", "alt"})


def recorded_python(actions: list[dict[str, Any]]) -> list[str]:
    """Render runtime actions as editable public API calls."""
    lines: list[str] = []
    for action in actions:
        path = action.get("path")
        control_id = action.get("controlId")
        kind = action.get("action")
        if not isinstance(kind, str):
            continue
        if isinstance(control_id, str) and control_id:
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
            "recording": recorded_python(actions if isinstance(actions, list) else []),
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
        action = request.get("action")
        if not isinstance(action, str):
            raise InputError("interactive action must be a string")
        result = self._perform_action(action, request)
        if action not in _ACTIONS_WITHOUT_AUTOMATIC_CAPTURE:
            self._capture(action)
        return result

    def _perform_action(self, action: str, request: dict[str, Any]) -> dict[str, Any]:
        if action == "reload":
            before = self.window.runtime.pid
            result = self.window.reload()
            return {
                "result": result,
                "processIdBefore": before,
                "processIdAfter": self.window.runtime.pid,
            }
        if action == "highlight":
            locator = self._optional_locator(request)
            return self.window.highlight(locator)
        if action == "pick":
            x = request.get("x")
            y = request.get("y")
            if (
                not isinstance(x, int)
                or isinstance(x, bool)
                or not isinstance(y, int)
                or isinstance(y, bool)
            ):
                raise InputError("pick coordinates must be integers")
            control = self.window.pick(x, y)
            self.window.highlight(self.window.locator(control.selector))
            return control.info
        if action == "resizeViewport":
            width = request.get("width")
            height = request.get("height")
            scale = request.get("uiScale")
            if not isinstance(width, int) or not isinstance(height, int):
                raise InputError("resize width and height must be integers")
            if not isinstance(scale, (int, float)):
                raise InputError("resize uiScale must be a number")
            return self.window.resize_viewport(width, height, ui_scale=float(scale))
        if action == "resizeSubject":
            width = request.get("width")
            height = request.get("height")
            if not isinstance(width, int) or not isinstance(height, int):
                raise InputError("subject width and height must be integers")
            return self.window.resize_subject(width, height)
        if action == "capture":
            return self._capture("manual")
        if action == "export":
            tree = self.window.query_tree()
            path = self.window.artifact_dir / "ui-tree-export.json"
            write_json(path, tree)
            return {"path": str(path)}
        if action == "click":
            return self._locator(request).click().data
        if action == "clickAt":
            x, y = self._coordinates(request, ("x", "y"))
            return self.window.click_at(x, y).data
        if action == "doubleClickAt":
            x, y = self._coordinates(request, ("x", "y"))
            return self.window.double_click_at(x, y).data
        if action == "rightClickAt":
            x, y = self._coordinates(request, ("x", "y"))
            return self.window.right_click_at(x, y).data
        if action == "drag":
            start_x, start_y, end_x, end_y = self._coordinates(
                request, ("startX", "startY", "endX", "endY")
            )
            return self.window.drag(start_x, start_y, end_x, end_y).data
        if action == "scrollAt":
            x, y, clicks = self._coordinates(request, ("x", "y", "clicks"))
            return self.window.scroll_at(x, y, clicks).data
        if action == "dragAndDrop":
            source_control_id = request.get("sourceControlId")
            target_control_id = request.get("targetControlId")
            if not isinstance(source_control_id, str) or not source_control_id:
                raise InputError("sourceControlId must be a non-empty string")
            if not isinstance(target_control_id, str) or not target_control_id:
                raise InputError("targetControlId must be a non-empty string")
            source = self.window.get_by_control_id(source_control_id)
            target = self.window.get_by_control_id(target_control_id)
            return source.drag_to(target).data
        if action == "fill":
            text = request.get("text")
            if not isinstance(text, str):
                raise InputError("fill text must be a string")
            return self._locator(request).fill(text).data
        if action == "type":
            text = request.get("text")
            if not isinstance(text, str) or not text:
                raise InputError("text must be a non-empty string")
            return self._locator(request).type_text(text).data
        if action == "press":
            key = request.get("key")
            if not isinstance(key, str) or not key:
                raise InputError("key must be a non-empty string")
            modifiers = request.get("modifiers", [])
            if not isinstance(modifiers, list) or any(
                not isinstance(modifier, str) or modifier not in _KEY_MODIFIERS
                for modifier in modifiers
            ):
                raise InputError("modifiers must contain only shift, control, and alt")
            return self._locator(request).press(key, modifiers=tuple(modifiers)).data
        if action == "replay":
            scenario_id = request.get("scenario")
            scenario = (
                self.scenarios.get(scenario_id)
                if isinstance(scenario_id, str)
                else None
            )
            if scenario is None:
                raise InputError(f"unknown scenario: {scenario_id}")
            return self._replay(scenario)
        if action == "switch":
            subject = request.get("subject")
            fixture_id = request.get("fixture")
            fixture = (
                self.fixtures.get(fixture_id)
                if isinstance(fixture_id, str) and fixture_id
                else None
            )
            if not isinstance(subject, str):
                raise InputError("subject must be a string")
            self.window.close()
            self.window = self._open(subject, fixture)
            self._latest_capture = None
            return {
                "subject": subject,
                "fixture": fixture_id or "",
                "processId": self.window.runtime.pid,
            }
        raise InputError(f"unknown interactive action: {action}")

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

    def _locator(self, request: dict[str, Any]) -> Locator:
        control_id = request.get("controlId")
        if isinstance(control_id, str) and control_id:
            return self.window.get_by_control_id(control_id)
        path = request.get("path")
        if not isinstance(path, str):
            raise InputError("action path must be a string")
        return self.window.get_by_path(path)

    def _optional_locator(self, request: dict[str, Any]) -> Locator | None:
        if request.get("controlId") or request.get("path"):
            return self._locator(request)
        return None

    @staticmethod
    def _coordinates(
        request: dict[str, Any], names: tuple[str, ...]
    ) -> tuple[int, ...]:
        values: list[int] = []
        for name in names:
            value = request.get(name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise InputError(f"{', '.join(names)} must be integers")
            values.append(value)
        return tuple(values)

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
            self._json(400, {"ok": False, "error": str(error)})

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
