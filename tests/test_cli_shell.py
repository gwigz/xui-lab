"""Shell-level CLI contract tests."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from xui_lab.session import (
    SessionFile,
    remove_session,
    serve_until_closed,
    socket_path,
    write_session,
)

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "xui-lab"


class ShellCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runtime_dir = Path(self.temporary.name) / "runtime data 测试"
        self.environment = {
            **os.environ,
            "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
            "XUI_LAB_RUNTIME_DIR": str(self.runtime_dir),
        }
        self._old_runtime_dir = os.environ.get("XUI_LAB_RUNTIME_DIR")
        os.environ["XUI_LAB_RUNTIME_DIR"] = str(self.runtime_dir)

    def tearDown(self) -> None:
        if self._old_runtime_dir is None:
            os.environ.pop("XUI_LAB_RUNTIME_DIR", None)
        else:
            os.environ["XUI_LAB_RUNTIME_DIR"] = self._old_runtime_dir

    def run_cli(
        self, *arguments: str, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *arguments],
            cwd=ROOT,
            env=self.environment,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    def session_record(self, session_id: str, *, pid: int) -> SessionFile:
        return SessionFile(
            schemaVersion=1,
            sessionId=session_id,
            token="secret",
            status="ready",
            socketPath=str(socket_path(session_id)),
            subject="test_widgets",
            runtime="/runtime",
            source="/source",
            fork="alchemy",
            artifacts="/artifacts",
            requestId="req_start",
            width=800,
            height=600,
            uiScale=1.0,
            capabilities=("input",),
            viewerSource=(),
            pid=pid,
        )

    def test_json_success_keeps_stdout_pure(self) -> None:
        result = self.run_cli("--request-id", "req_schema", "schema")

        self.assertEqual(0, result.returncode)
        self.assertEqual("", result.stderr)
        document = json.loads(result.stdout)
        self.assertEqual("req_schema", document["requestId"])
        self.assertEqual(result.stdout.rstrip() + "\n", result.stdout)

    def test_parse_failure_uses_status_two_and_stderr(self) -> None:
        result = self.run_cli("click", "--session", "sess_missing")

        self.assertEqual(2, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("one of the arguments", result.stderr)

    def test_accepted_failure_is_schema_valid_and_correlated(self) -> None:
        result = self.run_cli(
            "--request-id", "req_missing", "tree", "--session", "sess_missing"
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("session not found", result.stderr)
        document = json.loads(result.stdout)
        schema = json.loads((ROOT / "schemas" / "error.schema.json").read_text())
        Draft202012Validator(schema).validate(document)
        self.assertEqual("req_missing", document["requestId"])
        self.assertEqual("tree", document["operation"])

    def test_timeout_returns_runtime_failure(self) -> None:
        record = self.session_record("sess_timeout", pid=os.getpid())
        write_session(record)

        result = self.run_cli(
            "--request-id",
            "req_timeout",
            "--timeout",
            "0.05",
            "tree",
            "--session",
            record.session_id,
        )

        self.assertEqual(1, result.returncode)
        document = json.loads(result.stdout)
        self.assertEqual("runtime_failure", document["code"])
        self.assertEqual("req_timeout", document["requestId"])

    def test_status_removes_a_stale_session(self) -> None:
        record = self.session_record("sess_stale", pid=2**31 - 2)
        write_session(record)

        result = self.run_cli("session", "status")

        self.assertEqual(0, result.returncode)
        self.assertEqual([], json.loads(result.stdout)["sessions"])
        self.assertFalse((self.runtime_dir / "sessions" / "sess_stale.json").exists())

    def test_signal_termination_has_shell_status_and_no_partial_record(self) -> None:
        process = subprocess.Popen(
            [sys.executable, str(CLI), "session", "jsonl", "sess_wait"],
            cwd=ROOT,
            env=self.environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)

        self.assertEqual(-signal.SIGTERM, process.returncode)
        self.assertEqual("", stdout)
        self.assertEqual("", stderr)

    def test_record_accepts_output_paths_with_spaces_and_unicode(self) -> None:
        record = self.session_record("sess_record", pid=os.getpid())
        write_session(record)
        tree = {
            "control_id": "ok",
            "path": "/root/ok",
            "class": "LLButton",
            "label": "OK",
            "visible_chain": True,
            "enabled_chain": True,
            "children": [],
        }

        def handler(command: Any) -> dict[str, Any]:
            if command.command == "diagnostics":
                data = {"recording": [{"action": "click", "controlId": "ok"}]}
            elif command.command == "tree":
                data = {"tree": tree}
            else:
                data = {"closed": True}
            return {
                "schemaVersion": 1,
                "type": "result",
                "requestId": command.request_id,
                "operation": command.command,
                "data": data,
            }

        thread = threading.Thread(
            target=serve_until_closed, args=(record, handler), daemon=True
        )
        thread.start()
        output = Path(self.temporary.name) / "recordings with spaces" / "操作.json"
        try:
            result = self.run_cli(
                "record",
                "--session",
                record.session_id,
                "--output",
                str(output),
            )
        finally:
            remove_session(record.session_id)

        self.assertEqual(0, result.returncode, result.stderr)
        document = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual("role", document["commands"][0]["selector"]["kind"])


if __name__ == "__main__":
    unittest.main()
