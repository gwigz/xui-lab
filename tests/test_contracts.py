"""Tests for external Pydantic contracts and their domain conversions."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from xui_lab.contracts import (
    AdapterContract,
    ArtifactManifest,
    ControlIdSelectorContract,
    ErrorRecord,
    FixtureContract,
    ForkManifestContract,
    PathSelectorContract,
    ProgressEvent,
    ResultRecord,
    SelectorContract,
    contract_error,
    parse_cli_command,
    parse_interactive_action,
    parse_runtime_command,
    parse_runtime_response,
    schema_documents,
)
from xui_lab.errors import InputError

ROOT = Path(__file__).resolve().parents[1]


class StrictContractTests(unittest.TestCase):
    def test_selector_union_is_strict_discriminated_and_frozen(self) -> None:
        selector = SelectorContract.validate_python(
            {"schemaVersion": 1, "kind": "path", "path": "/root/button"}
        )

        self.assertIsInstance(selector, PathSelectorContract)
        with self.assertRaises(ValidationError):
            SelectorContract.validate_python(
                {
                    "schemaVersion": 1,
                    "kind": "path",
                    "path": "/root/button",
                    "surprise": True,
                }
            )
        with self.assertRaises(ValidationError):
            ControlIdSelectorContract(schemaVersion=1, kind="controlId", control_id=4)
        with self.assertRaises(ValidationError):
            selector.path = "/root/other"  # type: ignore[misc]

    def test_runtime_commands_reject_unknown_fields_and_invalid_variants(self) -> None:
        command = parse_runtime_command(
            {
                "schemaVersion": 1,
                "op": "input",
                "event": "click",
                "button": "left",
                "path": "/root/button",
            }
        )

        self.assertEqual("click", command.event)
        with self.assertRaises(InputError) as raised:
            parse_runtime_command(
                {
                    "schemaVersion": 1,
                    "op": "input",
                    "event": "click",
                    "button": "left",
                    "path": "/root/button",
                    "surprise": True,
                }
            )
        self.assertEqual(
            "runtime command violates the XUI Lab contract", str(raised.exception)
        )
        self.assertNotIn("extra_forbidden", str(raised.exception))

    def test_fixture_rejects_unknown_nested_fields_and_duplicate_ids(self) -> None:
        fixture = json.loads((ROOT / "fixtures/inventory-explorer.json").read_text())
        fixture["inventory"][0]["surprise"] = True
        with self.assertRaises(ValidationError):
            FixtureContract.model_validate(fixture)

        fixture["inventory"][0].pop("surprise")
        fixture["inventory"][1]["id"] = fixture["inventory"][0]["id"]
        with self.assertRaises(ValidationError):
            FixtureContract.model_validate(fixture)

    def test_public_records_reject_unknown_fields(self) -> None:
        with self.assertRaises(ValidationError):
            ResultRecord.model_validate(
                {
                    "schemaVersion": 1,
                    "type": "result",
                    "requestId": "req-1",
                    "operation": "tree",
                    "data": {},
                    "surprise": True,
                }
            )
        with self.assertRaises(ValidationError):
            ErrorRecord.model_validate(
                {
                    "schemaVersion": 1,
                    "type": "error",
                    "code": "invalid_contract",
                    "message": "request violates the XUI Lab contract",
                    "operation": "tree",
                    "retryable": False,
                    "surprise": True,
                }
            )
        with self.assertRaises(ValidationError):
            ArtifactManifest.model_validate(
                {
                    "schemaVersion": 1,
                    "artifactId": "run-1",
                    "fork": "alchemy",
                    "forkCommit": "a" * 40,
                    "subject": "test_widgets",
                    "artifacts": [],
                    "surprise": True,
                }
            )

    def test_validation_translation_is_stable(self) -> None:
        error = contract_error("fixture", operation="initialize")

        self.assertEqual(
            {
                "schemaVersion": 1,
                "type": "error",
                "code": "invalid_fixture",
                "message": "fixture violates the XUI Lab contract",
                "operation": "initialize",
                "retryable": False,
            },
            error.model_dump(mode="json", by_alias=True, exclude_none=True),
        )

    def test_repository_contracts_reject_unknown_top_level_fields(self) -> None:
        manifest = json.loads((ROOT / "forks.json").read_text())
        manifest["surprise"] = True
        with self.assertRaises(ValidationError):
            ForkManifestContract.model_validate(manifest)

        adapter = json.loads((ROOT / "adapters/alchemy/adapter.json").read_text())
        adapter["surprise"] = True
        with self.assertRaises(ValidationError):
            AdapterContract.model_validate(adapter)

    def test_event_and_transport_envelopes_are_closed(self) -> None:
        event = ProgressEvent(
            schemaVersion=1,
            type="event",
            event="progress",
            requestId="request-1",
            operation="capture",
            completed=1,
            total=2,
        )
        with self.assertRaises(ValidationError):
            type(event).model_validate(
                {
                    **event.model_dump(mode="json", by_alias=True),
                    "surprise": True,
                }
            )
        with self.assertRaises(InputError) as raised:
            parse_runtime_response({"ok": True, "result": {}, "surprise": True}, "tree")
        self.assertNotIn("extra_forbidden", str(raised.exception))

    def test_cli_and_socket_models_use_strict_scalar_types(self) -> None:
        with self.assertRaises(InputError):
            parse_cli_command(
                {
                    "schemaVersion": 1,
                    "command": "interactive",
                    "fork": None,
                    "viewerSource": [],
                    "subject": "test_widgets",
                    "runtime": None,
                    "fixture": None,
                    "width": True,
                    "height": 800,
                    "uiScale": 1.0,
                    "artifacts": "artifacts",
                    "artifactId": None,
                    "host": "127.0.0.1",
                    "port": 0,
                    "noBrowser": True,
                }
            )
        with self.assertRaises(InputError):
            parse_interactive_action(
                {
                    "schemaVersion": 1,
                    "action": "pick",
                    "x": True,
                    "y": 2,
                }
            )


class GeneratedSchemaTests(unittest.TestCase):
    def test_checked_in_schemas_match_models(self) -> None:
        for filename, document in schema_documents().items():
            with self.subTest(filename=filename):
                checked_in = json.loads((ROOT / "schemas" / filename).read_text())
                self.assertEqual(document, checked_in)


if __name__ == "__main__":
    unittest.main()
