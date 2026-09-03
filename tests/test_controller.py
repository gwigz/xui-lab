from __future__ import annotations

import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from xui_lab.api import Lab, artifact_directory
from xui_lab.cli import scenario_paths
from xui_lab.domain import Capability, Viewport
from xui_lab.errors import InputError, RuntimeFailure
from xui_lab.io import parse_manifest, read_json
from xui_lab.protocol import RuntimeProcess
from xui_lab.scenarios import Scenario, discover_scenarios, load_scenario

ROOT = Path(__file__).resolve().parents[1]


def fake_runtime(directory: Path, body: str) -> Path:
    executable = directory / "fake-runtime"
    executable.write_text(
        "#!/usr/bin/env python3\n" + textwrap.dedent(body), encoding="utf-8"
    )
    os.chmod(executable, 0o755)
    return executable


def close_quietly(runtime: RuntimeProcess) -> None:
    try:
        runtime.close()
    except RuntimeFailure:
        pass


class DomainTests(unittest.TestCase):
    def test_manifest_and_all_python_scenarios_load(self) -> None:
        manifest = parse_manifest(ROOT, read_json(ROOT / "forks.json"))
        self.assertEqual("alchemy", manifest.default_fork)
        scenarios = discover_scenarios(ROOT)
        self.assertTrue(scenarios)
        for scenario in scenarios.values():
            self.assertIn(scenario.fork, manifest.forks)

    def test_underscore_scenarios_load_but_stay_out_of_discovery(self) -> None:
        discovered = discover_scenarios(ROOT)
        discovered_paths = scenario_paths([])
        for path in sorted((ROOT / "tests" / "scenarios").glob("_*.py")):
            scenario = load_scenario(ROOT, path)
            self.assertNotIn(scenario.id, discovered)
            self.assertNotIn(path, discovered_paths)
            self.assertEqual([path], scenario_paths([str(path)]))

    def test_python_scenario_requires_one_scenario_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            path = Path(directory_text) / "invalid.py"
            path.write_text("SCENARIO = object()\n", encoding="utf-8")
            with self.assertRaisesRegex(InputError, "must define one SCENARIO"):
                load_scenario(ROOT, path)

    def test_artifact_directory_stays_beneath_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(InputError, "artifact root"):
                artifact_directory(root, "../outside")


class LabIsolationTests(unittest.TestCase):
    def test_invalid_fixture_is_rejected_before_runtime_starts(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            directory = Path(directory_text)
            fixture_data = read_json(ROOT / "fixtures/inventory-explorer.json")
            fixture_data["inventory"][0]["surprise"] = True
            fixture = directory / "invalid-fixture.json"
            fixture.write_text(json.dumps(fixture_data), encoding="utf-8")
            manifest = parse_manifest(ROOT, read_json(ROOT / "forks.json"))
            fork = manifest.forks[manifest.default_fork]
            lab = Lab(ROOT, fork, fork.source.path, directory / "runtime", directory)

            with (
                patch("xui_lab.api.RuntimeProcess") as runtime,
                self.assertRaisesRegex(InputError, "fixture violates"),
            ):
                lab.open(
                    artifact_id="invalid-fixture",
                    subject="test_widgets",
                    viewport=Viewport(100, 100, 1.0),
                    capabilities=frozenset(),
                    fixture=fixture,
                )

            runtime.assert_not_called()

    def test_each_scenario_uses_a_fresh_child_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            directory = Path(directory_text)
            process_log = directory / "processes.jsonl"
            executable = fake_runtime(
                directory,
                f"""
                import json
                import os
                import sys
                from pathlib import Path

                with Path({str(process_log)!r}).open("a", encoding="utf-8") as stream:
                    print(json.dumps({{"pid": os.getpid(), "parentPid": os.getppid()}}), file=stream)
                for line in sys.stdin:
                    command = json.loads(line)
                    if command["op"] == "initialize":
                        result = {{"supportedCapabilities": ["inspection"]}}
                    elif command["op"] == "installCapabilities":
                        result = {{
                            "capabilities": command["capabilities"],
                            "eventApis": {{}},
                            "inputOperations": [],
                        }}
                    else:
                        result = {{}}
                    print(json.dumps({{"ok": True, "result": result}}), flush=True)
                    if command["op"] == "shutdown":
                        break
            """,
            )
            manifest = parse_manifest(ROOT, read_json(ROOT / "forks.json"))
            fork = manifest.forks[manifest.default_fork]
            lab = Lab(
                ROOT,
                fork,
                fork.source.path,
                executable,
                directory / "artifacts",
            )

            def advance_one_frame(window):
                window.advance_frames(1)

            for scenario_id in ("fresh_process_one", "fresh_process_two"):
                scenario = Scenario(
                    id=scenario_id,
                    fork="alchemy",
                    subject="test_widgets",
                    viewport=Viewport(100, 100, 1.0),
                    capabilities=frozenset({Capability("inspection")}),
                    run=advance_one_frame,
                )
                with lab.open(
                    artifact_id=scenario.id,
                    subject=scenario.subject,
                    viewport=scenario.viewport,
                    capabilities=scenario.capabilities,
                ) as window:
                    scenario.run(window)

            processes = [
                json.loads(line)
                for line in process_log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(2, len(processes))
            self.assertEqual(2, len({process["pid"] for process in processes}))
            self.assertEqual(
                {os.getpid()}, {process["parentPid"] for process in processes}
            )


class RuntimeProcessTests(unittest.TestCase):
    def start(self, directory: Path, body: str) -> RuntimeProcess:
        runtime = RuntimeProcess(
            fake_runtime(directory, body),
            directory / "runtime.log",
            request_timeout=2.0,
            shutdown_timeout=2.0,
        )
        self.addCleanup(close_quietly, runtime)
        return runtime

    def test_request_reports_stalled_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            runtime = self.start(
                Path(directory_text),
                """
                import sys
                import time
                sys.stdin.readline()
                time.sleep(60)
            """,
            )
            with self.assertRaisesRegex(RuntimeFailure, "stalled.*query"):
                runtime.request({"op": "query", "kind": "tree"})

    def test_invalid_command_is_rejected_before_transport(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            directory = Path(directory_text)
            request_log = directory / "requests.jsonl"
            runtime = self.start(
                directory,
                f"""
                import json
                import sys
                from pathlib import Path

                for line in sys.stdin:
                    command = json.loads(line)
                    with Path({str(request_log)!r}).open("a", encoding="utf-8") as stream:
                        print(json.dumps(command), file=stream)
                    print(json.dumps({{"ok": True, "result": {{}}}}), flush=True)
                    if command["op"] == "shutdown":
                        break
            """,
            )

            with self.assertRaisesRegex(InputError, "runtime command violates"):
                runtime.request({"op": "notAnOperation"})
            self.assertEqual(0, runtime.close())

            requests = [
                json.loads(line)
                for line in request_log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(["shutdown"], [request["op"] for request in requests])

    def test_request_reports_runtime_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            runtime = self.start(
                Path(directory_text),
                """
                import sys
                sys.stdin.readline()
                raise SystemExit(7)
            """,
            )
            with self.assertRaisesRegex(RuntimeFailure, "exited with status 7"):
                runtime.request({"op": "query", "kind": "tree"})

    def test_request_reports_closed_response_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            runtime = self.start(
                Path(directory_text),
                """
                import os
                import sys
                import time
                sys.stdin.readline()
                os.close(sys.stdout.fileno())
                time.sleep(60)
            """,
            )
            with self.assertRaisesRegex(
                RuntimeFailure, "closed its response stream.*query"
            ):
                runtime.request({"op": "query", "kind": "tree"})

    def test_request_reports_invalid_json_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            runtime = self.start(
                Path(directory_text),
                """
                import sys
                sys.stdin.readline()
                print("not-json", flush=True)
            """,
            )
            with self.assertRaisesRegex(RuntimeFailure, "invalid response.*JSON"):
                runtime.request({"op": "query", "kind": "tree"})

    def test_request_reports_invalid_response_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            runtime = self.start(
                Path(directory_text),
                """
                import sys
                sys.stdin.readline()
                print("[]", flush=True)
            """,
            )
            with self.assertRaisesRegex(
                RuntimeFailure, "invalid response.*XUI Lab contract"
            ):
                runtime.request({"op": "query", "kind": "tree"})

    def test_shutdown_reports_runtime_that_does_not_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            runtime = self.start(
                Path(directory_text),
                """
                import json
                import sys
                import time
                for line in sys.stdin:
                    command = json.loads(line)
                    print(json.dumps({"ok": True, "result": {}}), flush=True)
                    if command["op"] == "shutdown":
                        time.sleep(60)
            """,
            )
            with self.assertRaisesRegex(RuntimeFailure, "stalled.*shutdown"):
                runtime.close()

    def test_clean_shutdown_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            runtime = self.start(
                Path(directory_text),
                """
                import json
                import sys
                for line in sys.stdin:
                    command = json.loads(line)
                    print(json.dumps({"ok": True, "result": {}}), flush=True)
                    if command["op"] == "shutdown":
                        break
            """,
            )
            self.assertEqual(0, runtime.close())

    def test_interactive_runtime_uses_the_headed_process_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            directory = Path(directory_text)
            argv_log = directory / "argv.json"
            executable = fake_runtime(
                directory,
                f"""
                import json
                import sys
                from pathlib import Path

                Path({str(argv_log)!r}).write_text(json.dumps(sys.argv), encoding="utf-8")
                for line in sys.stdin:
                    command = json.loads(line)
                    print(json.dumps({{"ok": True, "result": {{}}}}), flush=True)
                    if command["op"] == "shutdown":
                        break
            """,
            )
            runtime = RuntimeProcess(
                executable,
                directory / "runtime.log",
                mode="interactive",
                request_timeout=2.0,
                shutdown_timeout=2.0,
            )
            self.addCleanup(close_quietly, runtime)
            runtime.close()
            self.assertEqual(
                [str(executable), "--interactive"],
                json.loads(argv_log.read_text(encoding="utf-8")),
            )


if __name__ == "__main__":
    unittest.main()
