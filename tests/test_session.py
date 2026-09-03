"""Session lifecycle and one-shot CLI tests."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from xui_lab.cli import main, parse_command
from xui_lab.contracts import (
    ClickCliCommand,
    ReloadCliCommand,
    SessionCloseCliCommand,
    SessionStartCliCommand,
    TreeCliCommand,
)
from xui_lab.session import (
    SessionFile,
    cleanup_stale,
    pid_alive,
    remove_session,
    send_session_command,
    serve_until_closed,
    session_path,
    socket_path,
    write_session,
)


class SessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runtime = Path(self.temporary.name)
        self.enterContext = os.environ.setdefault
        self._old = os.environ.get("XUI_LAB_RUNTIME_DIR")
        os.environ["XUI_LAB_RUNTIME_DIR"] = str(self.runtime)

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("XUI_LAB_RUNTIME_DIR", None)
        else:
            os.environ["XUI_LAB_RUNTIME_DIR"] = self._old

    def test_close_is_idempotent_for_a_missing_session(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            status = main(["session", "close", "sess_missing"])
        self.assertEqual(0, status)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["closed"])
        self.assertFalse(payload["terminated"])

    def test_stale_ready_sessions_are_removed(self) -> None:
        record = SessionFile(
            schemaVersion=1,
            sessionId="sess_stale",
            token="token",
            status="ready",
            socketPath=str(socket_path("sess_stale")),
            subject="test_widgets",
            runtime="/runtime",
            source="/source",
            fork="alchemy",
            artifacts="/artifacts",
            requestId="req_1",
            width=100,
            height=100,
            uiScale=1.0,
            capabilities=("input",),
            viewerSource=(),
            pid=2**31 - 2,
        )
        write_session(record)
        removed = cleanup_stale()
        self.assertIn("sess_stale", removed)

    def test_socket_roundtrip_dispatches_a_close_command(self) -> None:
        session_id = "sess_live"
        record = SessionFile(
            schemaVersion=1,
            sessionId=session_id,
            token="secret-token",
            status="ready",
            socketPath=str(socket_path(session_id)),
            subject="test_widgets",
            runtime="/runtime",
            source="/source",
            fork="alchemy",
            artifacts="/artifacts",
            requestId="req_1",
            width=100,
            height=100,
            uiScale=1.0,
            capabilities=("input",),
            viewerSource=(),
            pid=os.getpid(),
        )
        write_session(record)
        seen: list[str] = []

        def handler(command: object) -> dict[str, object]:
            seen.append(type(command).__name__)
            return {"schemaVersion": 1, "type": "result", "ok": True}

        thread = threading.Thread(
            target=serve_until_closed, args=(record, handler), daemon=True
        )
        thread.start()
        try:
            response = send_session_command(
                session_id,
                {
                    "schemaVersion": 1,
                    "command": "session",
                    "sessionCommand": "close",
                    "sessionId": session_id,
                    "fork": None,
                    "viewerSource": [],
                    "requestId": "req_close",
                    "timeout": None,
                },
                timeout=5.0,
            )
        finally:
            thread.join(timeout=5.0)
            remove_session(session_id)
        self.assertEqual("result", response["type"])
        self.assertEqual(["SessionCloseCliCommand"], seen)

    def test_click_requires_one_selector_flag(self) -> None:
        with self.assertRaises(SystemExit):
            parse_command(["click", "--session", "sess_1"])
        with self.assertRaises(SystemExit):
            parse_command(
                [
                    "click",
                    "--session",
                    "sess_1",
                    "--control-id",
                    "a",
                    "--path",
                    "/root",
                ]
            )
        command = parse_command(["click", "--session", "sess_1", "--control-id", "ok"])
        self.assertIsInstance(command, ClickCliCommand)
        assert isinstance(command, ClickCliCommand)
        self.assertEqual("ok", command.control_id)
        self.assertEqual(
            {
                "schemaVersion": 1,
                "kind": "controlId",
                "controlId": "ok",
            },
            command.selector_contract().model_dump(mode="json", by_alias=True),
        )

    def test_session_start_parses_to_a_typed_command(self) -> None:
        command = parse_command(
            ["session", "start", "test_widgets", "--runtime", "/runtime"]
        )
        self.assertIsInstance(command, SessionStartCliCommand)
        assert isinstance(command, SessionStartCliCommand)
        self.assertEqual("test_widgets", command.subject)

    def test_tree_parses_include_tree_and_fields(self) -> None:
        command = parse_command(
            [
                "tree",
                "--session",
                "sess_1",
                "--include-tree",
                "--fields",
                "tree.path,treeArtifact.path",
            ]
        )
        self.assertIsInstance(command, TreeCliCommand)
        assert isinstance(command, TreeCliCommand)
        self.assertTrue(command.include_tree)
        self.assertEqual("tree.path,treeArtifact.path", command.fields)
        self.assertIsNone(command.jq)

    def test_tree_parses_jq_with_fields(self) -> None:
        command = parse_command(
            [
                "tree",
                "--session",
                "sess_1",
                "--fields",
                "tree.path",
                "--jq",
                ".data",
            ]
        )
        self.assertIsInstance(command, TreeCliCommand)
        assert isinstance(command, TreeCliCommand)
        self.assertEqual("tree.path", command.fields)
        self.assertEqual(".data", command.jq)

    def test_pid_alive_rejects_missing_processes(self) -> None:
        self.assertFalse(pid_alive(2**31 - 2))
        self.assertTrue(pid_alive(os.getpid()))

    def test_close_dry_run_does_not_remove_a_session(self) -> None:
        record = SessionFile(
            schemaVersion=1,
            sessionId="sess_dry",
            token="token",
            status="ready",
            socketPath=str(socket_path("sess_dry")),
            subject="test_widgets",
            runtime="/runtime",
            source="/source",
            fork="alchemy",
            artifacts="/artifacts",
            requestId="req_1",
            width=100,
            height=100,
            uiScale=1.0,
            capabilities=("input",),
            viewerSource=(),
            pid=os.getpid(),
        )
        write_session(record)
        stale = record.model_copy(
            update={
                "session_id": "sess_stale",
                "socket_path": str(socket_path("sess_stale")),
                "pid": 2**31 - 2,
            }
        )
        write_session(stale)
        stdout = StringIO()

        with redirect_stdout(stdout):
            status = main(["session", "close", "sess_dry", "--dry-run"])

        self.assertEqual(0, status)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["dryRun"])
        self.assertTrue(payload["wouldClose"])
        self.assertTrue(payload["wouldTerminate"])
        self.assertTrue(session_path("sess_dry").is_file())
        self.assertTrue(session_path("sess_stale").is_file())

    def test_close_dry_run_reports_a_missing_session(self) -> None:
        stdout = StringIO()
        with redirect_stdout(stdout):
            status = main(
                [
                    "session",
                    "close",
                    "sess_missing",
                    "--dry-run",
                    "--jq",
                    ".wouldClose",
                ]
            )
        self.assertEqual(0, status)
        self.assertEqual("false\n", stdout.getvalue())

    def test_reload_dry_run_does_not_contact_the_session(self) -> None:
        record = SessionFile(
            schemaVersion=1,
            sessionId="sess_reload",
            token="token",
            status="ready",
            socketPath=str(socket_path("sess_reload")),
            subject="test_widgets",
            runtime="/runtime",
            source="/source",
            fork="alchemy",
            artifacts="/artifacts",
            requestId="req_1",
            width=100,
            height=100,
            uiScale=1.0,
            capabilities=("input",),
            viewerSource=(),
            pid=os.getpid(),
        )
        write_session(record)
        stdout = StringIO()

        with redirect_stdout(stdout):
            status = main(
                ["reload", "--session", "sess_reload", "--dry-run", "--jq", ".data"]
            )

        self.assertEqual(0, status)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["dryRun"])
        self.assertTrue(payload["wouldReload"])
        self.assertEqual("sess_reload", payload["sessionId"])
        self.assertTrue(session_path("sess_reload").is_file())

    def test_reload_and_close_parse_dry_run(self) -> None:
        reload_command = parse_command(["reload", "--session", "sess_1", "--dry-run"])
        self.assertIsInstance(reload_command, ReloadCliCommand)
        assert isinstance(reload_command, ReloadCliCommand)
        self.assertTrue(reload_command.dry_run)

        close_command = parse_command(["session", "close", "sess_1", "--dry-run"])
        self.assertIsInstance(close_command, SessionCloseCliCommand)
        assert isinstance(close_command, SessionCloseCliCommand)
        self.assertTrue(close_command.dry_run)


if __name__ == "__main__":
    unittest.main()
