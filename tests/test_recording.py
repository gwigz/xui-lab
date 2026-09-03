"""Record and replay contract tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from xui_lab.cli import main, parse_command
from xui_lab.contracts import RecordCliCommand, ReplayCliCommand
from xui_lab.recording import recording_from_runtime

TREE = {
    "control_id": "root",
    "path": "/root",
    "class": "LLPanel",
    "visible_chain": True,
    "enabled_chain": True,
    "children": [
        {
            "control_id": "ok",
            "path": "/root/ok",
            "class": "LLButton",
            "label": "OK",
            "visible_chain": True,
            "enabled_chain": True,
            "children": [],
        }
    ],
}


class RecordingTests(unittest.TestCase):
    def test_commands_parse_to_typed_boundaries(self) -> None:
        record = parse_command(
            ["record", "--session", "sess_1", "--output", "actions.json"]
        )
        replay = parse_command(["replay", "actions.json", "--session", "sess_2"])

        self.assertIsInstance(record, RecordCliCommand)
        self.assertIsInstance(replay, ReplayCliCommand)

    def test_runtime_actions_become_selector_stable_commands(self) -> None:
        recording = recording_from_runtime(
            [{"action": "click", "controlId": "ok"}], TREE
        )

        self.assertEqual("recording", recording.type)
        self.assertEqual("click", recording.commands[0].command)
        self.assertEqual(
            {"schemaVersion": 1, "kind": "role", "role": "button", "name": "OK"},
            recording.commands[0].selector.model_dump(mode="json", by_alias=True),
        )

    def test_record_writes_a_reviewable_file_and_replay_preserves_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "commands 测试.json"
            diagnostics = {
                "type": "result",
                "data": {"recording": [{"action": "click", "controlId": "ok"}]},
            }
            tree = {"type": "result", "data": {"tree": TREE}}
            sent: list[dict[str, object]] = []

            def fake_send(
                _session: str, payload: dict[str, object], *, timeout: float
            ) -> dict[str, object]:
                sent.append(payload)
                return {
                    "schemaVersion": 1,
                    "type": "result",
                    "requestId": payload["requestId"],
                    "operation": payload["command"],
                    "data": {},
                }

            stdout = StringIO()
            with (
                patch(
                    "xui_lab.recording.send_session_command",
                    side_effect=[diagnostics, tree],
                ),
                redirect_stdout(stdout),
            ):
                status = main(
                    [
                        "--request-id",
                        "req_record",
                        "record",
                        "--session",
                        "sess_1",
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(0, status)
            document = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("recording", document["type"])
            self.assertNotIn("session", document["commands"][0])
            self.assertNotIn("controlId", document["commands"][0])

            with patch("xui_lab.recording.send_session_command", side_effect=fake_send):
                status = main(
                    [
                        "--request-id",
                        "req_replay",
                        "replay",
                        str(output),
                        "--session",
                        "sess_2",
                    ]
                )
            self.assertEqual(0, status)
            self.assertEqual(["click"], [item["command"] for item in sent])
            self.assertEqual("sess_2", sent[0]["session"])
            self.assertEqual("req_replay_1", sent[0]["requestId"])


if __name__ == "__main__":
    unittest.main()
