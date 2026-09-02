from __future__ import annotations

import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from xui_lab.api import Lab
from xui_lab.domain import Capability, Viewport, parse_manifest, parse_scenario
from xui_lab.errors import AssertionFailure, CapabilityError
from xui_lab.io import read_json
from xui_lab.operations import Frames, PathSelector, PointerAction

ROOT = Path(__file__).resolve().parents[1]
CHECKBOX_PATH = "/root/checkbox"


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

            def node(path, value, model_id=None, runtime_class="LLCheckBoxCtrl", source_line=12):
                result = {{
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
                    else:
                        value = bool(tree_version % 2) if subject == "unstable" else checked
                        children = [node({CHECKBOX_PATH!r}, value)]
                    result = {{"path": "/root", "class": "LLPanel", "children": children}}
                elif op == "query" and command["kind"] == "menus":
                    result = {{"visible": True, "menus": [{{"label": "Open"}}]}}
                elif op == "input":
                    checked = True
                    result = {{"handled": True, "path": command.get("path"), "event": command["event"]}}
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

    def test_model_id_locator_reports_every_ambiguous_match(self) -> None:
        with self.open("duplicates") as window:
            locator = window.get_by_model_id("11111111-1111-1111-1111-111111111111")
            with self.assertRaises(AssertionFailure) as raised:
                locator.resolve()
        message = str(raised.exception)
        self.assertIn("resolved to 2 controls", message)
        self.assertIn("/root/first (LLButton, floater_test.xml:21)", message)
        self.assertIn("/root/second (LLMenuItemGL, floater_test.xml:34)", message)

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

    def test_unavailable_actions_fail_before_dispatch(self) -> None:
        with self.open() as window:
            locator = window.get_by_path(CHECKBOX_PATH)
            other = window.get_by_path("/root/other")
            for action in (
                lambda: locator.fill("text"),
                lambda: locator.press("ENTER"),
                lambda: locator.scroll(3),
                lambda: locator.drag_to(other),
            ):
                with self.subTest(action=action):
                    with self.assertRaises(CapabilityError):
                        action()
        self.assertFalse(
            any(
                command.get("event") in {"fill", "key", "scroll", "drag"}
                for command in self.commands()
            )
        )

    def test_json_scenarios_parse_to_the_public_operation_types(self) -> None:
        scenario = parse_scenario(
            ROOT, read_json(ROOT / "scenarios" / "test-floater.json")
        )
        self.assertIsInstance(scenario.steps[0].operation, Frames)
        pointer = next(
            step.operation
            for step in scenario.steps
            if hasattr(step, "operation") and isinstance(step.operation, PointerAction)
        )
        self.assertIsInstance(pointer.selector, PathSelector)


if __name__ == "__main__":
    unittest.main()
