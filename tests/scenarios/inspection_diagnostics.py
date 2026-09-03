"""Prove layout diagnostics and capture sidecar fields from production state."""

from pathlib import Path
from typing import Any

from xui_lab import Capability, Scenario, Viewport, Window
from xui_lab.errors import AssertionFailure
from xui_lab.io import read_json


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise AssertionFailure(f"{field} must be a list, got {type(value).__name__}")
    return value


def run(window: Window) -> None:
    window.wait_for_stable()
    diagnostics = window.diagnostics()
    layout = diagnostics.get("layout")
    if not isinstance(layout, dict):
        raise AssertionFailure("diagnostics.layout is missing")
    _require_list(layout.get("overlaps"), "diagnostics.layout.overlaps")
    _require_list(layout.get("textClipping"), "diagnostics.layout.textClipping")
    if "graphics" not in diagnostics:
        raise AssertionFailure("diagnostics.graphics is missing")

    capture = window.capture("inspection-diagnostics")
    metadata = capture.get("metadata")
    if not isinstance(metadata, dict):
        sidecar = Path(str(capture.get("path", "")) + ".json")
        metadata = read_json(sidecar) if sidecar.is_file() else {}
    if not isinstance(metadata, dict):
        raise AssertionFailure("capture sidecar is missing")
    if not metadata.get("scenarioStep"):
        raise AssertionFailure("capture sidecar omitted scenarioStep")
    if not isinstance(metadata.get("graphics"), dict):
        raise AssertionFailure("capture sidecar omitted graphics")
    if metadata.get("sequence") != 1:
        raise AssertionFailure(
            f"capture sidecar sequence expected 1, got {metadata.get('sequence')!r}"
        )


SCENARIO = Scenario(
    id="inspection_diagnostics",
    fork="alchemy",
    subject="test_widgets",
    viewport=Viewport(1024, 700, 1.0),
    capabilities=frozenset({Capability("input"), Capability("inspection")}),
    run=run,
)
