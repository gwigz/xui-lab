"""Tests for jq filtering of CLI JSON documents."""

from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO

from xui_lab.errors import InputError
from xui_lab.json_output import compile_jq, emit_json_document, render_json


class JsonOutputTests(unittest.TestCase):
    def test_compile_rejects_an_invalid_expression(self) -> None:
        with self.assertRaises(InputError) as raised:
            compile_jq("not a jq program")
        self.assertIn("invalid --jq expression", str(raised.exception))

    def test_render_writes_strings_raw_and_values_compact(self) -> None:
        payload = {
            "sessionId": "sess_abc",
            "closed": True,
            "count": 2,
            "nested": {"path": "/root"},
        }

        self.assertEqual("sess_abc", render_json(payload, ".sessionId"))
        self.assertEqual("true", render_json(payload, ".closed"))
        self.assertEqual("2", render_json(payload, ".count"))
        self.assertEqual('{"path":"/root"}', render_json(payload, ".nested"))
        self.assertEqual(
            json.dumps(payload, separators=(",", ":")),
            render_json(payload, None),
        )

    def test_render_joins_multiple_results_and_empty_output(self) -> None:
        payload = {"names": ["ok", "cancel"]}

        self.assertEqual("ok\ncancel", render_json(payload, ".names[]"))
        self.assertEqual("", render_json({"names": []}, ".names[]"))

    def test_render_reports_jq_runtime_errors(self) -> None:
        with self.assertRaises(InputError) as raised:
            render_json({"n": 1}, ".n[]")
        self.assertIn("--jq failed", str(raised.exception))

    def test_error_records_are_not_filtered(self) -> None:
        payload = {
            "schemaVersion": 1,
            "type": "error",
            "code": "invalid_input",
            "message": "bad",
            "operation": "session",
            "retryable": False,
            "requestId": "req_1",
        }
        stdout = StringIO()

        with redirect_stdout(stdout):
            emit_json_document(payload, ".code")

        self.assertEqual(
            json.dumps(payload, separators=(",", ":")) + "\n",
            stdout.getvalue(),
        )

    def test_empty_jq_results_print_nothing(self) -> None:
        stdout = StringIO()

        with redirect_stdout(stdout):
            emit_json_document({"sessions": []}, ".sessions[]")

        self.assertEqual("", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
