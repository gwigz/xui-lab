#!/usr/bin/env python3
"""Exercise the headed runtime and write one machine-readable proof artifact."""

from __future__ import annotations

import argparse
import json
import math
import struct
import subprocess
import sys
import zlib
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
COLOR_SWATCH = "/Floater View/floater_test_widgets/group_tab_container/panel2/swatch1"


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


def scale_rectangle(rectangle: Any, scale: float) -> dict[str, int]:
    require(isinstance(rectangle, dict), "screen rectangle is missing")
    result: dict[str, int] = {}
    for key in ("left", "right", "bottom", "top"):
        value = rectangle.get(key)
        require(
            isinstance(value, int) and not isinstance(value, bool),
            "screen rectangle coordinates must be integers",
        )
        scaled = value * scale
        result[key] = (
            math.floor(scaled + 0.5) if scaled >= 0 else math.ceil(scaled - 0.5)
        )
    return result


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as image:
        header = image.read(24)
    require(header[:8] == b"\x89PNG\r\n\x1a\n", "capture is not a PNG")
    require(len(header) == 24 and header[12:16] == b"IHDR", "PNG header is incomplete")
    return struct.unpack(">II", header[16:24])


def png_pixel(path: Path, x: int, y: int) -> tuple[int, int, int, int]:
    data = path.read_bytes()
    require(data[:8] == b"\x89PNG\r\n\x1a\n", "capture is not a PNG")
    cursor = 8
    width = height = 0
    compressed = bytearray()
    while cursor < len(data):
        length = struct.unpack(">I", data[cursor : cursor + 4])[0]
        chunk_type = data[cursor + 4 : cursor + 8]
        chunk = data[cursor + 8 : cursor + 8 + length]
        cursor += length + 12
        if chunk_type == b"IHDR":
            width, height, depth, color, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", chunk)
            )
            require(
                (depth, color, compression, filtering, interlace) == (8, 6, 0, 0, 0),
                "capture is not an 8-bit non-interlaced RGBA PNG",
            )
        elif chunk_type == b"IDAT":
            compressed.extend(chunk)
        elif chunk_type == b"IEND":
            break

    require(0 <= x < width and 0 <= y < height, "pixel is outside the capture")
    decoded = zlib.decompress(compressed)
    stride = width * 4
    previous = bytearray(stride)
    offset = 0
    for row_index in range(height):
        filter_type = decoded[offset]
        row = bytearray(decoded[offset + 1 : offset + 1 + stride])
        offset += stride + 1
        for index, value in enumerate(row):
            left = row[index - 4] if index >= 4 else 0
            above = previous[index]
            upper_left = previous[index - 4] if index >= 4 else 0
            if filter_type == 1:
                row[index] = (value + left) & 0xFF
            elif filter_type == 2:
                row[index] = (value + above) & 0xFF
            elif filter_type == 3:
                row[index] = (value + ((left + above) // 2)) & 0xFF
            elif filter_type == 4:
                estimate = left + above - upper_left
                distances = (
                    abs(estimate - left),
                    abs(estimate - above),
                    abs(estimate - upper_left),
                )
                nearest = (left, above, upper_left)[distances.index(min(distances))]
                row[index] = (value + nearest) & 0xFF
            else:
                require(filter_type == 0, "capture uses an unknown PNG filter")
        if row_index == y:
            start = x * 4
            return tuple(row[start : start + 4])
        previous = row
    raise RuntimeError("capture omitted the requested pixel")


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
        initial_viewport = initial["viewport"]
        require(
            initial_viewport["windowWidth"] == 800
            and initial_viewport["windowHeight"] == 600,
            "initial window did not keep the requested screen size",
        )
        system_scale = initial_viewport["systemUIScale"]
        require(system_scale >= 1.0, "runtime reported an invalid system UI scale")
        require(
            initial_viewport["effectiveUIScale"] == system_scale,
            "initial effective UI scale omitted the system UI scale",
        )
        require(
            initial_viewport["lluiWidth"] == 800
            and initial_viewport["lluiHeight"] == 600,
            "initial LLUI size changed with the display density",
        )

        viewport = session.action(
            {"action": "resize", "width": 900, "height": 700, "uiScale": 1.25}
        )
        require(
            viewport["windowWidth"] == 900 and viewport["windowHeight"] == 700,
            "resize did not reach the requested screen size",
        )
        effective_scale = 1.25 * system_scale
        require(
            viewport["effectiveUIScale"] == effective_scale,
            "resize reported the wrong effective UI scale",
        )
        require(
            viewport["lluiWidth"] == round(viewport["pixelWidth"] / effective_scale)
            and viewport["lluiHeight"]
            == round(viewport["pixelHeight"] / effective_scale),
            "resize reported the wrong LLUI size",
        )

        line_editor = session.window.get_by_path(LINE_EDITOR)
        control = line_editor.resolve()
        swatch = session.window.get_by_path(COLOR_SWATCH).resolve()
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
        require(
            png_dimensions(Path(capture["path"]))
            == (viewport["pixelWidth"], viewport["pixelHeight"]),
            "capture dimensions do not match the Retina framebuffer",
        )
        overlay = capture["metadata"]["overlay"]
        require(overlay["included"] is False, "ordinary capture included live overlay")
        require(
            overlay["interactiveState"]["visible"] is True,
            "capture metadata omitted live overlay state",
        )
        swatch_rect = scale_rectangle(swatch.info.get("screen_rect"), effective_scale)
        swatch_x = (swatch_rect["left"] + swatch_rect["right"]) // 2
        swatch_y = (
            viewport["pixelHeight"]
            - 1
            - (swatch_rect["bottom"] + swatch_rect["top"]) // 2
        )
        swatch_pixel = png_pixel(Path(capture["path"]), swatch_x, swatch_y)
        red, green, blue, alpha = swatch_pixel
        require(
            red >= 40 and green - red >= 35 and blue - green >= 35 and alpha >= 250,
            f"color swatch rendered the wrong pixel: {swatch_pixel}",
        )
        highlighted_capture = session.window.capture(
            "headed-with-capture-highlight", highlight=line_editor
        )
        highlighted_overlay = highlighted_capture["metadata"]["overlay"]
        require(
            highlighted_overlay.get("framebufferRect")
            == scale_rectangle(control.info.get("screen_rect"), effective_scale),
            "capture highlight did not convert its screen rectangle to framebuffer coordinates",
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
                "swatchPixel": swatch_pixel,
                "highlightedCapture": highlighted_capture,
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
