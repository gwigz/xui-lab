from __future__ import annotations

import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from xui_lab.domain import AssertionStep, Comparison, parse_manifest, parse_scenario
from xui_lab.errors import AssertionFailure, InputError, RuntimeFailure
from xui_lab.io import read_json
from xui_lab.protocol import RuntimeProcess
from xui_lab.runner import ScenarioRunner, artifact_directory, check_assertion, resolve_pointer


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
    def test_manifest_and_all_scenarios_parse(self) -> None:
        manifest = parse_manifest(ROOT, read_json(ROOT / "forks.json"))
        self.assertEqual("alchemy", manifest.default_fork)
        for path in (ROOT / "scenarios").glob("*.json"):
            scenario = parse_scenario(ROOT, read_json(path), str(path))
            self.assertIn(scenario.fork, manifest.forks)

    def test_scenario_rejects_unknown_keys(self) -> None:
        raw = read_json(ROOT / "scenarios" / "test-floater.json")
        raw["typo"] = True
        with self.assertRaisesRegex(InputError, "unknown keys"):
            parse_scenario(ROOT, raw)

    def test_scenario_rejects_artifact_path_escape(self) -> None:
        raw = read_json(ROOT / "scenarios" / "test-floater.json")
        raw["id"] = "../outside"
        with self.assertRaisesRegex(InputError, "invalid format"):
            parse_scenario(ROOT, raw)

    def test_scenario_rejects_capture_paths_outside_artifact_directory(self) -> None:
        rejected_commands = (
            {"op": "capture", "path": "/tmp/frame.png"},
            {"op": "capture", "path": "C:\\temp\\frame.png"},
            {"op": "capture", "path": "../frame.png"},
            {"op": "capture", "path": "nested\\..\\frame.png"},
            {"op": "capture", "name": "nested/frame"},
            {"op": "capture", "name": "C:frame"},
        )
        for command in rejected_commands:
            with self.subTest(command=command):
                raw = read_json(ROOT / "scenarios" / "test-floater.json")
                raw["steps"] = [command]
                with self.assertRaisesRegex(InputError, "capture"):
                    parse_scenario(ROOT, raw)

    def test_artifact_directory_stays_beneath_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(InputError, "artifact root"):
                artifact_directory(root, "../outside")

    def test_json_pointer_decodes_tokens(self) -> None:
        self.assertEqual(4, resolve_pointer({"a/b": {"~key": 4}}, "/a~1b/~0key"))

    def test_structural_assertion_failure_is_specific(self) -> None:
        step = AssertionStep("query", "/enabled", Comparison.EQUALS, True)
        with self.assertRaisesRegex(AssertionFailure, "expected True, got False"):
            check_assertion(step, {"query": {"enabled": False}})


class ScenarioRunnerTests(unittest.TestCase):
    def test_each_scenario_uses_a_fresh_child_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            directory = Path(directory_text)
            process_log = directory / "processes.jsonl"
            executable = fake_runtime(directory, f"""
                import json
                import os
                import sys
                from pathlib import Path

                with Path({str(process_log)!r}).open("a", encoding="utf-8") as stream:
                    print(json.dumps({{"pid": os.getpid(), "parentPid": os.getppid()}}), file=stream)
                for line in sys.stdin:
                    command = json.loads(line)
                    result = {{"capabilities": ["inspection"]}} if command["op"] == "initialize" else {{}}
                    print(json.dumps({{"ok": True, "result": result}}), flush=True)
                    if command["op"] == "shutdown":
                        break
            """)
            manifest = parse_manifest(ROOT, read_json(ROOT / "forks.json"))
            fork = manifest.forks[manifest.default_fork]
            runner = ScenarioRunner(ROOT, fork, fork.source.path, executable, directory / "artifacts")

            for scenario_id in ("fresh_process_one", "fresh_process_two"):
                scenario = parse_scenario(ROOT, {
                    "schemaVersion": 1,
                    "id": scenario_id,
                    "fork": "alchemy",
                    "subject": "test_widgets",
                    "viewport": {"width": 100, "height": 100, "uiScale": 1.0},
                    "requires": ["inspection"],
                    "steps": [{"op": "frames", "count": 1}],
                })
                self.assertTrue(runner.run(scenario).passed)

            processes = [json.loads(line) for line in process_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(2, len(processes))
            self.assertEqual(2, len({process["pid"] for process in processes}))
            self.assertEqual({os.getpid()}, {process["parentPid"] for process in processes})


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
            runtime = self.start(Path(directory_text), """
                import sys
                import time
                sys.stdin.readline()
                time.sleep(60)
            """)
            with self.assertRaisesRegex(RuntimeFailure, "stalled.*query"):
                runtime.request({"op": "query"})

    def test_request_reports_runtime_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            runtime = self.start(Path(directory_text), """
                import sys
                sys.stdin.readline()
                raise SystemExit(7)
            """)
            with self.assertRaisesRegex(RuntimeFailure, "exited with status 7"):
                runtime.request({"op": "query"})

    def test_request_reports_closed_response_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            runtime = self.start(Path(directory_text), """
                import os
                import sys
                import time
                sys.stdin.readline()
                os.close(sys.stdout.fileno())
                time.sleep(60)
            """)
            with self.assertRaisesRegex(RuntimeFailure, "closed its response stream.*query"):
                runtime.request({"op": "query"})

    def test_request_reports_invalid_json_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            runtime = self.start(Path(directory_text), """
                import sys
                sys.stdin.readline()
                print("not-json", flush=True)
            """)
            with self.assertRaisesRegex(RuntimeFailure, "invalid response.*JSON"):
                runtime.request({"op": "query"})

    def test_request_reports_invalid_response_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            runtime = self.start(Path(directory_text), """
                import sys
                sys.stdin.readline()
                print("[]", flush=True)
            """)
            with self.assertRaisesRegex(RuntimeFailure, "invalid response.*Boolean 'ok'"):
                runtime.request({"op": "query"})

    def test_shutdown_reports_runtime_that_does_not_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            runtime = self.start(Path(directory_text), """
                import json
                import sys
                import time
                for line in sys.stdin:
                    command = json.loads(line)
                    print(json.dumps({"ok": True, "result": {}}), flush=True)
                    if command["op"] == "shutdown":
                        time.sleep(60)
            """)
            with self.assertRaisesRegex(RuntimeFailure, "stalled.*shutdown"):
                runtime.close()

    def test_clean_shutdown_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            runtime = self.start(Path(directory_text), """
                import json
                import sys
                for line in sys.stdin:
                    command = json.loads(line)
                    print(json.dumps({"ok": True, "result": {}}), flush=True)
                    if command["op"] == "shutdown":
                        break
            """)
            self.assertEqual(0, runtime.close())

if __name__ == "__main__":
    unittest.main()
