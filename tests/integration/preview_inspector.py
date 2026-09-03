#!/usr/bin/env python3
"""Run the built inspector against a deterministic local session stub."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xui_lab.inspector_http import serve_inspector  # noqa: E402


class PreviewSession:
    def __init__(self, capture: Path | None):
        self.latest_capture = capture

    def capture_path(self, version: int) -> Path | None:
        if self.latest_capture is None or version != 1:
            return None
        return self.latest_capture

    def close(self) -> None:
        return

    def action(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("action") == "pick":
            return {"path": "/Floater View/test_floater/content/save_button"}
        return {"preview": True, **request}

    def state(self) -> dict[str, Any]:
        selected = "/Floater View/test_floater/content/save_button"
        return {
            "tree": {
                "control_id": "root",
                "path": "/Floater View",
                "class": "LLView",
                "children": [
                    {
                        "control_id": "floater",
                        "path": "/Floater View/test_floater",
                        "name": "test_floater",
                        "class": "LLFloater",
                        "children": [
                            {
                                "control_id": "content",
                                "path": "/Floater View/test_floater/content",
                                "name": "content",
                                "class": "LLPanel",
                                "children": [
                                    {
                                        "control_id": "save-button",
                                        "path": selected,
                                        "name": "save_button",
                                        "label": "Save",
                                        "class": "LLButton",
                                        "enabled": True,
                                        "visible": True,
                                        "children": [],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            "diagnostics": {
                "processId": 4242,
                "focus": selected,
                "mouseCapture": None,
                "viewport": {"width": 800, "height": 600, "uiScale": 1},
                "overlay": {"path": selected, "visible": True},
            },
            "recording": [
                f"window.get_by_path({selected!r}).click()",
                f"window.get_by_path({selected!r}).press('Enter')",
            ],
            "locators": {
                "save-button": {
                    "selector": {
                        "schemaVersion": 1,
                        "kind": "role",
                        "role": "button",
                        "name": "Save",
                    },
                    "python": "window.get_by_role('button', name='Save')",
                    "kind": "role",
                    "matchCount": 1,
                    "signals": ["role", "name"],
                    "fallbackReason": None,
                }
            },
            "artifactDir": "/tmp/xui-lab-inspector-preview",
            "subjects": ["test_widgets", "inventory_explorer"],
            "fixtures": ["inventory-explorer"],
            "scenarios": ["test_floater", "inventory_explorer"],
            "inputOperations": ["click", "fill", "key"],
            "capture": {
                "available": self.latest_capture is not None,
                "version": 1 if self.latest_capture is not None else 0,
            },
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    capture = args.capture.expanduser().resolve() if args.capture is not None else None
    if capture is not None and (
        not capture.is_file() or capture.suffix.lower() != ".png"
    ):
        raise SystemExit(f"capture must be an existing PNG: {capture}")
    return serve_inspector(
        PreviewSession(capture),
        host=args.host,
        port=args.port,
        open_browser=args.open_browser,
    )


if __name__ == "__main__":
    raise SystemExit(main())
