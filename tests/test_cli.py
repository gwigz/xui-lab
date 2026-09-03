"""Tests for the command-line contract."""

from __future__ import annotations

import json
import os
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from xui_lab.cli import dispatch, main, parse_command, parser
from xui_lab.contracts import (
    ErrorRecord,
    InteractiveCliCommand,
    OperationsContract,
    PreflightCliCommand,
    PreflightContract,
    SchemaCatalogContract,
    SubjectsCliCommand,
    SubjectsContract,
    schema_documents,
)


def fake_metadata_runtime(
    directory: Path, *, fork: str, commit: str, extra: dict[str, object] | None = None
) -> Path:
    payload = {
        "fork": fork,
        "forkCommit": commit,
        "protocolVersion": 1,
        **(extra or {}),
    }
    executable = directory / "fake-runtime"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        + textwrap.dedent(
            f"""
            import json
            import sys

            if sys.argv[1:] == ["--metadata"]:
                print(json.dumps({payload!r}))
                raise SystemExit(0)
            raise SystemExit(2)
            """
        ),
        encoding="utf-8",
    )
    os.chmod(executable, 0o755)
    return executable


class CommandLineTests(unittest.TestCase):
    def test_interactive_default_viewport_fits_the_test_floater(self) -> None:
        args = parser().parse_args(["interactive", "test_widgets"])

        self.assertEqual((1200, 800), (args.width, args.height))

    def test_argparse_values_become_a_typed_command(self) -> None:
        command = parse_command(["interactive", "test_widgets"])

        self.assertIsInstance(command, InteractiveCliCommand)
        assert isinstance(command, InteractiveCliCommand)
        self.assertEqual("test_widgets", command.subject)
        self.assertEqual((1200, 800), (command.width, command.height))
        self.assertIsInstance(command.viewer_source, tuple)
        self.assertTrue(command.request_id.startswith("req_"))

        with patch("xui_lab.cli.cmd_interactive", return_value=0) as handler:
            self.assertEqual(0, dispatch(command))
        handler.assert_called_once_with(command)

    def test_operations_json_discovers_queries_inputs_and_arguments(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(["--request-id", "req_operations", "operations", "--json"])

        self.assertEqual(0, status)
        self.assertEqual("", stderr.getvalue())
        self.assertEqual(1, stdout.getvalue().count("\n"))
        document = OperationsContract.model_validate_json(stdout.getvalue())
        self.assertEqual("req_operations", document.request_id)
        operations = {operation.name: operation for operation in document.operations}
        self.assertEqual(
            {
                "tree",
                "menus",
                "inventory",
                "value",
                "click",
                "doubleClick",
                "rightClick",
                "fill",
                "text",
                "key",
                "scroll",
                "drag",
                "dragAndDrop",
            },
            operations.keys(),
        )
        self.assertEqual(("inspection",), operations["tree"].required_capabilities)
        self.assertEqual(
            ("input", "inventory_model"),
            operations["dragAndDrop"].required_capabilities,
        )
        self.assertEqual(2, len(operations["drag"].argument_sets))
        self.assertEqual(
            ["source", "target"],
            [argument.name for argument in operations["dragAndDrop"].argument_sets[0]],
        )
        json.loads(stdout.getvalue())

    def test_subjects_json_lists_declared_subjects_without_a_runtime(self) -> None:
        stdout = StringIO()

        with redirect_stdout(stdout):
            status = main(["subjects", "--json"])

        self.assertEqual(0, status)
        document = SubjectsContract.model_validate_json(stdout.getvalue())
        self.assertEqual("alchemy", document.fork)
        self.assertIsNone(document.runtime)
        self.assertEqual("Alchemy", document.source.display_name)
        self.assertEqual("adapters/alchemy", document.source.adapter)
        self.assertEqual("indra/newview", document.source.resource_root)
        self.assertFalse(document.source.overridden)
        self.assertRegex(document.source.commit, r"^[0-9a-f]{40}$")
        self.assertEqual(
            ["test_widgets"], [subject.name for subject in document.subjects]
        )
        subject = document.subjects[0]
        self.assertEqual(("input", "inspection"), subject.required_capabilities)
        self.assertFalse(subject.openable)
        self.assertEqual("runtime_not_selected", subject.unavailable_reason)

    def test_subjects_json_records_an_overridden_viewer_source(self) -> None:
        listed = StringIO()
        with redirect_stdout(listed):
            self.assertEqual(0, main(["subjects", "--json"]))
        catalog = SubjectsContract.model_validate_json(listed.getvalue())

        stdout = StringIO()
        with redirect_stdout(stdout):
            status = main(
                [
                    "--viewer-source",
                    f"alchemy={catalog.source.path}",
                    "subjects",
                    "--json",
                ]
            )

        self.assertEqual(0, status)
        document = SubjectsContract.model_validate_json(stdout.getvalue())
        self.assertTrue(document.source.overridden)
        self.assertEqual(catalog.source.path, document.source.path)
        self.assertEqual(catalog.source.commit, document.source.commit)

    def test_subjects_json_marks_openable_when_runtime_metadata_matches(self) -> None:
        listed = StringIO()
        with redirect_stdout(listed):
            self.assertEqual(0, main(["subjects", "--json"]))
        catalog = SubjectsContract.model_validate_json(listed.getvalue())

        with tempfile.TemporaryDirectory() as directory_text:
            executable = fake_metadata_runtime(
                Path(directory_text),
                fork=catalog.fork,
                commit=catalog.source.commit,
                extra={"surprise": True},
            )
            runtime_path = str(executable.resolve())
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(["subjects", "--json", "--runtime", runtime_path])

        self.assertEqual(0, status)
        document = SubjectsContract.model_validate_json(stdout.getvalue())
        assert document.runtime is not None
        self.assertEqual(runtime_path, document.runtime.path)
        self.assertEqual(catalog.fork, document.runtime.fork)
        self.assertEqual(catalog.source.commit, document.runtime.commit)
        self.assertTrue(document.runtime.matched)
        self.assertTrue(document.subjects[0].openable)
        self.assertIsNone(document.subjects[0].unavailable_reason)

    def test_subjects_json_reports_source_mismatch_for_a_stale_runtime(self) -> None:
        listed = StringIO()
        with redirect_stdout(listed):
            self.assertEqual(0, main(["subjects", "--json"]))
        catalog = SubjectsContract.model_validate_json(listed.getvalue())

        with tempfile.TemporaryDirectory() as directory_text:
            executable = fake_metadata_runtime(
                Path(directory_text),
                fork=catalog.fork,
                commit="0" * 40,
            )
            stdout = StringIO()
            with redirect_stdout(stdout):
                status = main(["subjects", "--json", "--runtime", str(executable)])

        self.assertEqual(0, status)
        document = SubjectsContract.model_validate_json(stdout.getvalue())
        assert document.runtime is not None
        self.assertFalse(document.runtime.matched)
        self.assertFalse(document.subjects[0].openable)
        self.assertEqual("source_mismatch", document.subjects[0].unavailable_reason)

    def test_subjects_json_rejects_invalid_runtime_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory_text:
            executable = Path(directory_text) / "fake-runtime"
            executable.write_text(
                "#!/usr/bin/env python3\nprint('not-json')\n", encoding="utf-8"
            )
            os.chmod(executable, 0o755)
            stderr = StringIO()
            stdout = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status = main(
                    [
                        "--request-id",
                        "req_metadata",
                        "subjects",
                        "--json",
                        "--runtime",
                        str(executable),
                    ]
                )

        self.assertEqual(1, status)
        self.assertIn("invalid JSON", stderr.getvalue())
        record = ErrorRecord.model_validate_json(stdout.getvalue())
        self.assertEqual("runtime_failure", record.code)
        self.assertEqual("subjects", record.operation)
        self.assertEqual("req_metadata", record.request_id)
        self.assertFalse(record.retryable)

    def test_subjects_json_rejects_a_missing_runtime(self) -> None:
        stderr = StringIO()
        stdout = StringIO()
        missing = Path("/no/such/xui-lab-runtime")

        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(
                [
                    "--request-id",
                    "req_missing",
                    "subjects",
                    "--json",
                    "--runtime",
                    str(missing),
                ]
            )

        self.assertEqual(2, status)
        self.assertIn("runtime executable not found", stderr.getvalue())
        record = ErrorRecord.model_validate_json(stdout.getvalue())
        self.assertEqual("invalid_input", record.code)
        self.assertEqual("subjects", record.operation)
        self.assertEqual("req_missing", record.request_id)
        self.assertFalse(record.retryable)

    def test_subjects_requires_json_output(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            parser().parse_args(["subjects"])

        self.assertEqual(2, raised.exception.code)

        command = parse_command(["subjects", "--json"])
        self.assertIsInstance(command, SubjectsCliCommand)
        assert isinstance(command, SubjectsCliCommand)
        self.assertIsNone(command.runtime)
        self.assertTrue(command.request_id)
        with patch("xui_lab.cli.cmd_subjects", return_value=0) as handler:
            self.assertEqual(0, dispatch(command))
        handler.assert_called_once_with(command)

    def test_preflight_json_suggests_operations_when_a_capability_is_missing(
        self,
    ) -> None:
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(
                [
                    "--request-id",
                    "req_preflight",
                    "preflight",
                    "--json",
                    "--subject",
                    "test_widgets",
                    "--operation",
                    "dragAndDrop",
                ]
            )

        self.assertEqual(1, status)
        self.assertEqual("", stderr.getvalue())
        document = PreflightContract.model_validate_json(stdout.getvalue())
        self.assertEqual("req_preflight", document.request_id)
        self.assertEqual("test_widgets", document.subject)
        self.assertEqual(("input", "inspection"), document.capabilities.available)
        self.assertEqual((), document.capabilities.missing)
        operations = {item.name: item for item in document.operations}
        self.assertTrue(operations["click"].available)
        self.assertFalse(operations["dragAndDrop"].available)
        self.assertEqual(
            ("inventory_model",), operations["dragAndDrop"].missing_capabilities
        )
        self.assertEqual(
            "missing_capability", operations["dragAndDrop"].unavailable_reason
        )
        self.assertIn("click", operations["dragAndDrop"].suggested_operations)
        self.assertIn("tree", operations["dragAndDrop"].suggested_operations)
        self.assertNotIn("inventory", operations["dragAndDrop"].suggested_operations)
        self.assertNotIn("menus", operations["dragAndDrop"].suggested_operations)

    def test_preflight_json_accepts_an_available_operation(self) -> None:
        stdout = StringIO()

        with redirect_stdout(stdout):
            status = main(
                [
                    "preflight",
                    "--json",
                    "--subject",
                    "test_widgets",
                    "--operation",
                    "click",
                ]
            )

        self.assertEqual(0, status)
        document = PreflightContract.model_validate_json(stdout.getvalue())
        click = next(item for item in document.operations if item.name == "click")
        self.assertTrue(click.available)
        self.assertEqual((), click.suggested_operations)

    def test_preflight_json_rejects_an_unknown_operation(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(["preflight", "--json", "--operation", "teleport"])

        self.assertEqual(2, status)
        self.assertIn("unknown operation", stderr.getvalue())
        record = ErrorRecord.model_validate_json(stdout.getvalue())
        self.assertEqual("invalid_input", record.code)
        self.assertEqual("preflight", record.operation)

    def test_preflight_json_rejects_an_unknown_subject(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = main(["preflight", "--json", "--subject", "inventory_explorer"])

        self.assertEqual(2, status)
        self.assertIn("not declared", stderr.getvalue())
        record = ErrorRecord.model_validate_json(stdout.getvalue())
        self.assertEqual("invalid_input", record.code)
        self.assertEqual("preflight", record.operation)

    def test_preflight_parses_to_a_typed_command(self) -> None:
        command = parse_command(
            ["preflight", "--json", "--subject", "test_widgets", "--operation", "click"]
        )

        self.assertIsInstance(command, PreflightCliCommand)
        assert isinstance(command, PreflightCliCommand)
        self.assertEqual("test_widgets", command.subject)
        self.assertEqual("click", command.operation)

    def test_schema_emits_every_generated_contract(self) -> None:
        stdout = StringIO()

        with redirect_stdout(stdout):
            status = main(["schema"])

        self.assertEqual(0, status)
        catalog = SchemaCatalogContract.model_validate_json(stdout.getvalue())
        self.assertEqual(schema_documents(), catalog.schemas)
        self.assertTrue(catalog.request_id)
        self.assertTrue(
            {
                "command.schema.json",
                "result.schema.json",
                "event.schema.json",
                "error.schema.json",
                "tree-node.schema.json",
                "selector.schema.json",
                "subjects.schema.json",
                "preflight.schema.json",
                "artifact-manifest.schema.json",
            }
            <= catalog.schemas.keys()
        )


if __name__ == "__main__":
    unittest.main()
