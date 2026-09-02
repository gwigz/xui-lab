#!/usr/bin/env python3
"""Exercise the headed runtime and write one machine-readable proof artifact."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from xui_lab.api import Lab
from xui_lab.domain import Capability, ForkId, Viewport, parse_manifest
from xui_lab.interactive import (
    InteractiveConfig,
    InteractiveSession,
    discover_fixtures,
)
from xui_lab.io import git_commit, read_json, write_json
from xui_lab.scenarios import discover_scenarios

ROOT = Path(__file__).resolve().parents[2]
LINE_EDITOR = "/Floater View/floater_test_widgets/test_line_editor"
CHECKBOX_BUTTON = "/Floater View/floater_test_widgets/test_checkbox/CheckboxCtrl Button"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def runtime_metadata(executable: Path) -> dict[str, Any]:
    result = subprocess.run(
        [str(executable), "--metadata"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(result.stdout)
    require(isinstance(value, dict), "runtime metadata must be an object")
    return value


def rectangle_center(rectangle: Any) -> tuple[int, int]:
    require(isinstance(rectangle, dict), "screen rectangle is missing")
    values = [rectangle.get(key) for key in ("left", "right", "bottom", "top")]
    require(
        all(isinstance(value, int) and not isinstance(value, bool) for value in values),
        "screen rectangle coordinates must be integers",
    )
    left, right, bottom, top = values
    return ((left + right) // 2, (bottom + top) // 2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--viewer-source", type=Path, default=ROOT / "viewers/alchemy")
    parser.add_argument("--artifacts", type=Path, default=ROOT / "artifacts/headed")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    executable = args.runtime.expanduser().resolve()
    viewer_source = args.viewer_source.expanduser().resolve()
    artifact_root = args.artifacts.expanduser().resolve()
    require(executable.is_file(), f"runtime executable not found: {executable}")

    manifest = parse_manifest(ROOT, read_json(ROOT / "forks.json"))
    fork = manifest.forks[ForkId("alchemy")]
    commit = git_commit(viewer_source)
    metadata = runtime_metadata(executable)
    require(metadata.get("forkCommit") == commit, "runtime/viewer commit mismatch")

    capabilities = frozenset({Capability("input"), Capability("inspection")})
    lab = Lab(ROOT, fork, viewer_source, executable, artifact_root)
    session = InteractiveSession(
        lab,
        InteractiveConfig(
            subject="test_widgets",
            viewport=Viewport(800, 600, 1.0),
            fixture=None,
            artifact_id="headed-verification",
        ),
        {"test_widgets": capabilities},
        discover_fixtures(ROOT),
        discover_scenarios(ROOT, "alchemy"),
    )

    proof: dict[str, Any] = {"forkCommit": commit}
    try:
        initial = session.window.diagnostics()
        process_id = session.window.runtime.pid
        require(initial["processId"] == process_id, "runtime PID diagnostic mismatch")

        viewport = session.action(
            {"action": "resize", "width": 900, "height": 700, "uiScale": 1.25}
        )
        require(
            viewport["pixelWidth"] == 900 and viewport["pixelHeight"] == 700,
            "resize did not reach the requested pixel size",
        )
        require(
            viewport["lluiWidth"] == 720 and viewport["lluiHeight"] == 560,
            "resize reported the wrong LLUI size",
        )

        control = session.window.get_by_path(LINE_EDITOR).resolve()
        x, y = rectangle_center(control.info.get("screen_rect"))
        picked = session.window.pick(x, y)
        require(
            picked.path == LINE_EDITOR, "picking did not return the frontmost editor"
        )
        for field in ("class", "source_file", "local_rect", "screen_rect"):
            require(field in picked.info, f"pick result is missing {field}")
        require(
            isinstance(picked.info.get("hit_test_order"), list),
            "pick result is missing hit-test order",
        )

        session.window.highlight(session.window.get_by_path(LINE_EDITOR))
        capture = session.window.capture("headed-with-live-highlight")
        overlay = capture["metadata"]["overlay"]
        require(overlay["included"] is False, "ordinary capture included live overlay")
        require(
            overlay["interactiveState"]["visible"] is True,
            "capture metadata omitted live overlay state",
        )

        filled = session.window.get_by_path(LINE_EDITOR).fill("headed input").data
        pressed = session.window.get_by_path(LINE_EDITOR).press("Enter").data
        clicked = session.window.get_by_path(CHECKBOX_BUTTON).click().data
        for name, result in (("fill", filled), ("key", pressed), ("click", clicked)):
            for field in (
                "focusBefore",
                "focusAfter",
                "focusChanged",
                "mouseCaptureBefore",
                "mouseCaptureAfter",
                "mouseCaptureChanged",
            ):
                require(field in result, f"{name} result is missing {field}")

        reload_result = session.action({"action": "reload"})
        require(
            reload_result["processIdBefore"]
            == reload_result["processIdAfter"]
            == process_id,
            "interactive reload restarted the runtime",
        )
        replay = session.action({"action": "replay", "scenario": "test_floater"})
        require(replay["passed"] is True, "scenario replay failed")
        require(
            replay["processIdBefore"] == replay["processIdAfter"] == process_id,
            "scenario replay restarted the runtime",
        )

        export = session.action({"action": "export"})
        require(Path(export["path"]).is_file(), "UI-tree export was not written")
        state = session.state()
        recording = state["recording"]
        require(any("fill(" in line for line in recording), "recorder omitted fill")
        require(
            any("press(" in line for line in recording), "recorder omitted key input"
        )

        proof.update(
            {
                "processId": process_id,
                "viewport": viewport,
                "pick": picked.info,
                "capture": capture,
                "reload": reload_result,
                "replay": replay,
                "recording": recording,
                "tree": session.window.query_tree(),
                "uiTreeExport": export["path"],
            }
        )
        proof_path = session.window.artifact_dir / "headed-verification.json"
        write_json(proof_path, proof)
        print(json.dumps({"passed": True, "proof": str(proof_path)}, sort_keys=True))
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
