from __future__ import annotations

import json
import os
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

from xui_lab.api import Lab
from xui_lab.domain import Capability, Viewport, parse_manifest
from xui_lab.errors import AssertionFailure, RuntimeFailure
from xui_lab.interactive import (
    InspectorHandler,
    InspectorServer,
    InteractiveConfig,
    InteractiveSession,
    recorded_python,
)
from xui_lab.io import read_json
from xui_lab.scenarios import load_scenario

ROOT = Path(__file__).resolve().parents[1]
CHECKBOX_PATH = "/root/checkbox"
PRODUCTION_CHECKBOX = "/Floater View/floater_test_widgets/test_checkbox"
PRODUCTION_CHECKBOX_BUTTON = f"{PRODUCTION_CHECKBOX}/CheckboxCtrl Button"
RESIZE_HANDLE_PATH = "/root/resize_handle"


def fake_runtime(directory: Path, command_log: Path) -> Path:
    executable = directory / "fake-api-runtime"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        + textwrap.dedent(f"""
            import json
            import sys
            from pathlib import Path

            checked = False
            subject = ""
            tree_version = 0

            def node(path, value, model_id=None, runtime_class="LLCheckBoxCtrl", source_line=12, control_id=None):
                result = {{
                    "control_id": control_id or f"control-{{source_line}}",
                    "path": path,
                    "class": runtime_class,
                    "source_file": "floater_test.xml",
                    "source_line": source_line,
                    "visible": True,
                    "visible_chain": True,
                    "enabled": True,
                    "enabled_chain": True,
                    "keyboard_focus": value,
                    "selected": value,
                    "value": value,
                    "local_rect": {{"left": 0, "right": 10, "top": 10, "bottom": 0}},
                    "screen_rect": {{"left": 5, "right": 15, "top": 15, "bottom": 5}},
                    "clipping_rect": {{"left": 5, "right": 15, "top": 15, "bottom": 5}},
                    "children": [],
                }}
                if model_id is not None:
                    result["model_id"] = model_id
                return result

            for line in sys.stdin:
                command = json.loads(line)
                with Path({str(command_log)!r}).open("a", encoding="utf-8") as stream:
                    print(json.dumps(command), file=stream)
                op = command["op"]
                if op == "initialize":
                    subject = command["subject"]
                    result = {{"supportedCapabilities": ["input", "inspection", "menus", "external_effects"]}}
                elif op == "installCapabilities":
                    result = {{
                        "capabilities": command["capabilities"],
                        "eventApis": {{
                            "LLWindow": {{"operations": [{{"name": "getSubtree"}}, {{"name": "mouseDown"}}]}},
                            "XUILab": {{"operations": [{{"name": "query"}}, {{"name": "input"}}]}},
                        }},
                        "inputOperations": ["click", "doubleClick", "rightClick", "fill", "text", "key", "drag"],
                    }}
                elif op == "stable":
                    result = {{"stable": subject != "unstable", "frames": command["maximumFrames"]}}
                elif op == "frames":
                    result = {{"frames": command["count"]}}
                elif op == "query" and command["kind"] == "tree":
                    tree_version += 1
                    if subject == "duplicates":
                        children = [
                            node("/root/first", False, "11111111-1111-1111-1111-111111111111", "LLButton", 21),
                            node("/root/second", False, "11111111-1111-1111-1111-111111111111", "LLMenuItemGL", 34),
                        ]
                    elif subject == "duplicate_paths":
                        children = [
                            node({RESIZE_HANDLE_PATH!r}, False, runtime_class="LLResizeHandle", source_line=41, control_id="handle-top-left"),
                            node({RESIZE_HANDLE_PATH!r}, False, runtime_class="LLResizeHandle", source_line=42, control_id="handle-bottom-right"),
                        ]
                    else:
                        value = bool(tree_version % 2) if subject == "unstable" else checked
                        children = [node({CHECKBOX_PATH!r}, value)]
                        if subject != "unstable":
                            children.extend([
                                node({PRODUCTION_CHECKBOX!r}, value),
                                node({PRODUCTION_CHECKBOX_BUTTON!r}, value, runtime_class="LLButton"),
                            ])
                    result = {{"control_id": "root", "path": "/root", "class": "LLPanel", "children": children}}
                elif op == "query" and command["kind"] == "menus":
                    result = {{"visible": True, "menus": [{{"label": "Open"}}]}}
                elif op == "input":
                    checked = True
                    result = {{
                        "handled": True,
                        "path": command.get("path"),
                        "controlId": command.get("controlId"),
                        "event": command["event"],
                        "focusBefore": None,
                        "focusAfter": {{"path": command.get("path")}},
                        "focusChanged": True,
                        "mouseCaptureBefore": None,
                        "mouseCaptureAfter": None,
                        "mouseCaptureChanged": False,
                    }}
                elif op == "pick":
                    result = {{"control_id": "control-12", "path": {CHECKBOX_PATH!r}, "class": "LLCheckBoxCtrl"}}
                elif op == "highlight":
                    result = {{"visible": command.get("target") is not None}}
                elif op == "resizeViewport":
                    result = {{"pixelWidth": command["width"], "pixelHeight": command["height"]}}
                elif op == "resizeSubject":
                    result = {{"width": command["width"], "height": command["height"]}}
                elif op == "reload":
                    checked = False
                    result = {{"subject": subject}}
                elif op == "diagnostics":
                    result = {{"effects": [{{"kind": "url", "value": "https://example.test"}}]}}
                elif op == "capture":
                    result = {{"path": str(Path(command.get("name", "frame")).with_suffix(".png"))}}
                elif op == "shutdown":
                    result = {{"shutdown": True}}
                else:
                    result = {{}}
                print(json.dumps({{"ok": True, "result": result}}), flush=True)
                if op == "shutdown":
                    break
        """),
        encoding="utf-8",
    )
    os.chmod(executable, 0o755)
    return executable


class PlaywrightApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.command_log = self.directory / "commands.jsonl"
        manifest = parse_manifest(ROOT, read_json(ROOT / "forks.json"))
        self.fork = manifest.forks[manifest.default_fork]
        self.lab = Lab(
            ROOT,
            self.fork,
            self.fork.source.path,
            fake_runtime(self.directory, self.command_log),
            self.directory / "artifacts",
        )

    def open(self, subject: str = "test_widgets"):
        return self.lab.open(
            artifact_id=f"python_api_{subject}",
            subject=subject,
            viewport=Viewport(320, 240, 1.0),
            capabilities=frozenset(
                {
                    Capability("input"),
                    Capability("inspection"),
                    Capability("menus"),
                    Capability("external_effects"),
                }
            ),
        )

    def commands(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in self.command_log.read_text(encoding="utf-8").splitlines()
        ]

    def test_locator_resolves_before_each_action_and_expectation(self) -> None:
        with self.open() as window:
            checkbox = window.get_by_path(CHECKBOX_PATH)
            checkbox.expect_visible()
            checkbox.expect_enabled()
            checkbox.expect_value(False)
            checkbox.expect_selected(False)
            checkbox.expect_focused(False)
            checkbox.expect_local_rect({"left": 0, "right": 10, "top": 10, "bottom": 0})
            checkbox.expect_screen_rect(
                {"left": 5, "right": 15, "top": 15, "bottom": 5}
            )
            checkbox.expect_clipping_rect(
                {"left": 5, "right": 15, "top": 15, "bottom": 5}
            )
            action = checkbox.click()
            action.expect_handled()
            checkbox.expect_value(True)
            window.expect_menu_visible()
            window.expect_recorded_effect("kind", "url")
            self.assertEqual(
                True, window.raw({"op": "diagnostics"})["effects"][0]["kind"] == "url"
            )

        commands = self.commands()
        input_index = next(
            index for index, command in enumerate(commands) if command["op"] == "input"
        )
        self.assertEqual("query", commands[input_index - 1]["op"])
        self.assertEqual("stable", commands[input_index - 2]["op"])
        self.assertEqual("stable", commands[input_index + 1]["op"])
        self.assertGreaterEqual(
            sum(command["op"] == "query" for command in commands), 4
        )
        self.assertTrue(
            (
                self.directory
                / "artifacts"
                / "python_api_test_widgets"
                / "event-trace.json"
            ).is_file()
        )

    def test_supported_pointer_actions_use_the_same_input_operation(self) -> None:
        with self.open() as window:
            locator = window.get_by_path(CHECKBOX_PATH)
            locator.double_click().expect_handled()
            locator.right_click().expect_handled()
        inputs = [command for command in self.commands() if command["op"] == "input"]
        self.assertEqual(
            [("doubleClick", "left"), ("click", "right")],
            [(command["event"], command["button"]) for command in inputs],
        )

    def test_coordinate_right_click_uses_the_shared_input_operation(self) -> None:
        with self.open() as window:
            window.right_click_at(40, 30).expect_handled()

        pointer_input = next(
            command for command in self.commands() if command["op"] == "input"
        )
        self.assertEqual("click", pointer_input["event"])
        self.assertEqual("right", pointer_input["button"])
        self.assertEqual((40, 30), (pointer_input["x"], pointer_input["y"]))

    def test_model_id_locator_reports_every_ambiguous_match(self) -> None:
        with self.open("duplicates") as window:
            locator = window.get_by_model_id("11111111-1111-1111-1111-111111111111")
            with self.assertRaises(AssertionFailure) as raised:
                locator.resolve()
        message = str(raised.exception)
        self.assertIn("resolved to 2 controls", message)
        self.assertIn("/root/first (LLButton, floater_test.xml:21)", message)
        self.assertIn("/root/second (LLMenuItemGL, floater_test.xml:34)", message)

    def test_control_id_locator_distinguishes_duplicate_paths(self) -> None:
        with self.open("duplicate_paths") as window:
            handle = window.get_by_control_id("handle-bottom-right")
            self.assertEqual("handle-bottom-right", handle.resolve().control_id)
            handle.drag_by(dx=40, dy=-30).expect_handled()

        drag = next(
            command
            for command in self.commands()
            if command.get("op") == "input" and command.get("event") == "drag"
        )
        self.assertEqual("handle-bottom-right", drag["controlId"])
        self.assertEqual((40, -30), (drag["deltaX"], drag["deltaY"]))

    def test_missing_locator_reports_zero_matches(self) -> None:
        with self.open() as window:
            with self.assertRaisesRegex(AssertionFailure, "resolved to 0 controls"):
                window.get_by_path("/root/missing").resolve()

    def test_stability_timeout_reports_changing_paths(self) -> None:
        artifact_dir = self.directory / "artifacts" / "python_api_unstable"
        with self.assertRaisesRegex(
            AssertionFailure, r"did not stabilize.*changing paths: /root/checkbox"
        ):
            with self.open("unstable") as window:
                window.get_by_path(CHECKBOX_PATH).expect_visible()
        self.assertFalse(read_json(artifact_dir / "diagnostics.json")["passed"])
        self.assertTrue((artifact_dir / "ui-tree.json").is_file())
        self.assertTrue((artifact_dir / "diagnostics-runtime.json").is_file())

    def test_keyboard_and_text_actions_use_the_shared_input_operation(self) -> None:
        with self.open() as window:
            locator = window.get_by_path(CHECKBOX_PATH)
            locator.fill("Known text").expect_handled()
            locator.press("Enter").expect_handled()
        inputs = [command for command in self.commands() if command["op"] == "input"]
        self.assertEqual(["fill", "key"], [command["event"] for command in inputs])
        self.assertEqual("Known text", inputs[0]["text"])
        self.assertEqual("Enter", inputs[1]["key"])

    def test_window_exposes_runtime_operations_without_command_objects(self) -> None:
        with self.open() as window:
            self.assertEqual(3, window.advance_frames(3)["frames"])
            self.assertEqual(640, window.resize_viewport(640, 480)["pixelWidth"])
            self.assertEqual(900, window.resize_subject(900, 520)["width"])
            self.assertEqual("test_widgets", window.reload()["subject"])
            self.assertEqual("/root", window.query_tree()["path"])
            self.assertIn("effects", window.diagnostics())
            capture = window.capture(
                "public-api", highlight=window.get_by_path(CHECKBOX_PATH)
            )
            self.assertEqual("public-api.png", capture["path"])

        capture_command = next(
            command for command in self.commands() if command["op"] == "capture"
        )
        self.assertEqual({"path": CHECKBOX_PATH}, capture_command["highlight"])
        self.assertTrue(capture_command["includeOverlay"])

        operations = [command["op"] for command in self.commands()]
        self.assertIn("resizeViewport", operations)
        self.assertIn("resizeSubject", operations)
        self.assertNotIn("resize", operations)

    def test_recorded_actions_render_as_editable_locator_calls(self) -> None:
        self.assertEqual(
            [
                f"window.get_by_path({CHECKBOX_PATH!r}).click()",
                f"window.get_by_path({CHECKBOX_PATH!r}).fill('hello')",
                f"window.get_by_path({CHECKBOX_PATH!r}).press('Enter')",
                "window.get_by_control_id('resize-handle').drag_by(dx=40, dy=-30)",
            ],
            recorded_python(
                [
                    {"action": "click", "path": CHECKBOX_PATH},
                    {"action": "fill", "path": CHECKBOX_PATH, "text": "hello"},
                    {"action": "key", "path": CHECKBOX_PATH, "key": "Enter"},
                    {
                        "action": "drag",
                        "path": RESIZE_HANDLE_PATH,
                        "controlId": "resize-handle",
                        "deltaX": 40,
                        "deltaY": -30,
                    },
                ]
            ),
        )

    def test_interactive_capture_is_available_to_the_browser(self) -> None:
        capture = self.directory / "artifacts" / "latest.png"
        capture.parent.mkdir(parents=True)
        capture.write_bytes(b"png bytes")
        session = object.__new__(InteractiveSession)
        session.window = type(
            "WindowStub",
            (),
            {
                "artifact_dir": capture.parent,
                "capture": staticmethod(lambda _name: {"path": str(capture)}),
            },
        )()
        session._latest_capture = None
        session._capture_version = 0

        result = session.action({"action": "capture"})

        self.assertEqual(str(capture), result["path"])
        self.assertEqual(capture.resolve(), session.latest_capture)
        self.assertEqual(1, session._capture_version)

    def test_interactive_session_starts_with_a_browser_capture(self) -> None:
        capture = self.directory / "artifacts" / "initial.png"
        capture.parent.mkdir(parents=True)
        capture.write_bytes(b"png bytes")
        capture_names: list[str] = []

        class WindowStub:
            def __init__(self) -> None:
                self.artifact_dir = capture.parent

            def capture(self, name: str) -> dict[str, str]:
                capture_names.append(name)
                return {"path": str(capture)}

        class LabStub:
            @staticmethod
            def open(**_kwargs: object) -> WindowStub:
                return WindowStub()

        session = InteractiveSession(
            LabStub(),
            InteractiveConfig(
                subject="test_widgets",
                viewport=Viewport(320, 240, 1.0),
                fixture=None,
                artifact_id="automatic-capture",
            ),
            {"test_widgets": frozenset()},
            {},
            {},
        )

        self.assertEqual(1, len(capture_names))
        self.assertEqual(capture.resolve(), session.latest_capture)
        self.assertEqual(1, session._capture_version)

    def test_interactive_inputs_refresh_the_browser_capture(self) -> None:
        capture = self.directory / "artifacts" / "latest.png"
        capture.parent.mkdir(parents=True)
        capture.write_bytes(b"png bytes")
        capture_names: list[str] = []

        class ActionStub:
            data = {"handled": True}

        class LocatorStub:
            @staticmethod
            def click() -> ActionStub:
                return ActionStub()

            @staticmethod
            def fill(_text: str) -> ActionStub:
                return ActionStub()

            @staticmethod
            def press(_key: str) -> ActionStub:
                return ActionStub()

        class WindowStub:
            def __init__(self) -> None:
                self.artifact_dir = capture.parent

            def capture(self, name: str) -> dict[str, str]:
                capture_names.append(name)
                return {"path": str(capture)}

            @staticmethod
            def get_by_control_id(_control_id: str) -> LocatorStub:
                return LocatorStub()

            @staticmethod
            def click_at(_x: int, _y: int) -> ActionStub:
                return ActionStub()

            @staticmethod
            def right_click_at(_x: int, _y: int) -> ActionStub:
                return ActionStub()

            @staticmethod
            def drag(
                _start_x: int, _start_y: int, _end_x: int, _end_y: int
            ) -> ActionStub:
                return ActionStub()

        session = object.__new__(InteractiveSession)
        session.window = WindowStub()
        session.scenarios = {"test_floater": object()}
        session._replay = lambda _scenario: {"passed": True}
        session._latest_capture = None
        session._capture_version = 0

        session.action({"action": "click", "controlId": "checkbox"})
        session.action({"action": "press", "controlId": "line-editor", "key": "Enter"})
        session.action({"action": "replay", "scenario": "test_floater"})
        session.action({"action": "clickAt", "x": 10, "y": 20})
        session.action({"action": "rightClickAt", "x": 10, "y": 20})
        session.action(
            {
                "action": "drag",
                "startX": 10,
                "startY": 20,
                "endX": 40,
                "endY": 50,
            }
        )
        session.action(
            {"action": "fill", "controlId": "line-editor", "text": "Known text"}
        )

        self.assertEqual(7, len(capture_names))
        self.assertEqual(capture.resolve(), session.latest_capture)
        self.assertEqual(7, session._capture_version)

    def test_interactive_capture_rejects_a_path_outside_its_artifacts(self) -> None:
        capture = self.directory / "outside.png"
        capture.write_bytes(b"png bytes")
        artifact_dir = self.directory / "artifacts"
        artifact_dir.mkdir()
        session = object.__new__(InteractiveSession)
        session.window = type(
            "WindowStub",
            (),
            {
                "artifact_dir": artifact_dir,
                "capture": staticmethod(lambda _name: {"path": str(capture)}),
            },
        )()
        session._latest_capture = None
        session._capture_version = 0

        with self.assertRaisesRegex(RuntimeFailure, "outside the artifact directory"):
            session.action({"action": "capture"})

    def test_inspector_serves_the_latest_capture_as_an_image(self) -> None:
        capture = self.directory / "latest.png"
        capture.write_bytes(b"png bytes")
        server = InspectorServer(("127.0.0.1", 0), InspectorHandler)
        server.session = type("SessionStub", (), {"latest_capture": capture})()
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        try:
            host, port = server.server_address
            with urlopen(f"http://{host}:{port}/api/capture", timeout=2) as response:
                self.assertEqual("image/png", response.headers.get_content_type())
                self.assertEqual(b"png bytes", response.read())
        finally:
            thread.join(timeout=2)
            server.server_close()

    def test_inspector_serves_the_built_react_client(self) -> None:
        server = InspectorServer(("127.0.0.1", 0), InspectorHandler)
        server.session = type("SessionStub", (), {})()
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        try:
            host, port = server.server_address
            with urlopen(f"http://{host}:{port}/", timeout=2) as response:
                body = response.read().decode()
                self.assertEqual("text/html", response.headers.get_content_type())
                self.assertIn('<div id="root"></div>', body)
                self.assertIn("/assets/app.js", body)
        finally:
            thread.join(timeout=2)
            server.server_close()

    def test_python_scenario_runs_through_window_and_locator(self) -> None:
        scenario = load_scenario(ROOT, ROOT / "tests" / "scenarios" / "test_floater.py")
        with self.lab.open(
            artifact_id="python_scenario",
            subject=scenario.subject,
            viewport=scenario.viewport,
            capabilities=scenario.capabilities,
            fixture=scenario.fixture,
        ) as window:
            scenario.run(window)

        commands = self.commands()
        self.assertTrue(any(command["op"] == "resizeViewport" for command in commands))
        self.assertTrue(any(command["op"] == "reload" for command in commands))
        self.assertTrue(any(command["op"] == "capture" for command in commands))


if __name__ == "__main__":
    unittest.main()
