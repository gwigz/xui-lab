from __future__ import annotations

import unittest
from typing import Any

from xui_lab.layout import analyze_layout_diagnostics


def rect(left: int, right: int, bottom: int, top: int) -> dict[str, int]:
    return {"left": left, "right": right, "bottom": bottom, "top": top}


def node(
    control_id: str,
    path: str,
    runtime_class: str,
    *,
    local: dict[str, int] | None = None,
    screen: dict[str, int] | None = None,
    clipping: dict[str, int] | None = None,
    children: list[dict[str, Any]] | None = None,
    source_file: str = "floater_test.xml",
) -> dict[str, Any]:
    return {
        "control_id": control_id,
        "path": path,
        "class": runtime_class,
        "source_file": source_file,
        "source_line": len(control_id),
        "visible_chain": True,
        "local_rect": local or rect(0, 100, 0, 100),
        "screen_rect": screen or rect(0, 100, 0, 100),
        "clipping_rect": clipping or rect(0, 100, 0, 100),
        "children": children or [],
    }


class LayoutDiagnosticsTests(unittest.TestCase):
    def test_reports_invalid_rectangles_and_parent_overflow_with_context(self) -> None:
        child = node(
            "child",
            "/Floater View/floater/child",
            "9LLTextBox",
            local=rect(12, 4, 0, 10),
            screen=rect(5, 105, 5, 20),
            clipping=rect(5, 100, 5, 20),
        )
        parent = node(
            "floater",
            "/Floater View/floater",
            "9LLFloater",
            screen=rect(0, 100, 0, 100),
            clipping=rect(0, 100, 0, 100),
            children=[
                child,
                node(
                    "rounded",
                    "/Floater View/floater/rounded",
                    "13LLLayoutPanel",
                    screen=rect(0, 101, 0, 100),
                    clipping=rect(0, 100, 0, 100),
                ),
            ],
        )
        tree = node(
            "floater-view",
            "/Floater View",
            "13LLFloaterView",
            children=[parent],
        )

        layout = analyze_layout_diagnostics(tree, {})

        self.assertEqual(2, layout["actionableCount"])
        invalid = layout["invalidRectangles"][0]
        self.assertEqual("localRect", invalid["rectangle"])
        self.assertEqual("/Floater View/floater/child", invalid["path"])
        self.assertEqual("floater_test.xml", invalid["sourceFile"])
        self.assertEqual(rect(12, 4, 0, 10), invalid["localRect"])
        self.assertEqual(
            ["/Floater View", "/Floater View/floater"],
            [ancestor["path"] for ancestor in invalid["ancestors"]],
        )
        outside = layout["outsideParent"][0]
        self.assertEqual("/Floater View/floater", outside["parentPath"])
        self.assertEqual(rect(0, 100, 0, 100), outside["parentClippingRect"])
        self.assertEqual(rect(5, 105, 5, 20), outside["screenRect"])

    def test_suppresses_host_overlap_and_offscreen_scroll_descendant(self) -> None:
        offscreen = node(
            "label",
            "/Floater View/floater/list/panel/label",
            "9LLTextBox",
            screen=rect(10, 70, -10, 5),
            clipping=rect(10, 70, 0, 5),
        )
        panel = node(
            "panel",
            "/Floater View/floater/list/panel",
            "7LLPanel",
            children=[offscreen],
        )
        scroll = node(
            "list",
            "/Floater View/floater/list",
            "14LLFlatListView",
            children=[panel],
        )
        generated = node(
            "generated",
            "/Floater View/floater/generated",
            "6LLView",
            local=rect(0, 100, 0, -4),
            screen=rect(-5, 105, 0, 100),
            source_file="",
        )
        floater = node(
            "floater",
            "/Floater View/floater",
            "9LLFloater",
            children=[scroll, generated],
        )
        floater_view = node(
            "floater-view",
            "/Floater View",
            "13LLFloaterView",
            children=[floater],
        )
        menu_holder = node("menu-holder", "/Menu Holder", "12LLMenuHolderGL")
        tree = node("root", "", "7LLPanel", children=[menu_holder, floater_view])
        raw = {
            "overlaps": [
                {
                    "controlId": "menu-holder",
                    "path": "/Menu Holder",
                    "otherControlId": "floater-view",
                    "otherPath": "/Floater View",
                    "rect": rect(0, 100, 0, 100),
                }
            ],
            "textClipping": [
                {
                    "controlId": "label",
                    "path": offscreen["path"],
                    "textWidth": 60,
                    "textHeight": 15,
                    "clippingRect": rect(10, 70, 0, 5),
                }
            ],
        }

        layout = analyze_layout_diagnostics(tree, raw)

        self.assertEqual(0, layout["actionableCount"])
        self.assertEqual([], layout["overlaps"])
        self.assertEqual([], layout["textClipping"])
        self.assertEqual([], layout["outsideParent"])

    def test_enriches_text_clipping_and_both_sides_of_an_overlap(self) -> None:
        left = node("left", "/Floater View/floater/left", "9LLTextBox")
        right = node("right", "/Floater View/floater/right", "8LLButton")
        floater = node(
            "floater",
            "/Floater View/floater",
            "9LLFloater",
            children=[left, right],
        )
        tree = node(
            "floater-view",
            "/Floater View",
            "13LLFloaterView",
            children=[floater],
        )
        raw = {
            "overlaps": [
                {
                    "controlId": "left",
                    "path": left["path"],
                    "otherControlId": "right",
                    "otherPath": right["path"],
                    "rect": rect(40, 60, 0, 20),
                }
            ],
            "textClipping": [
                {
                    "controlId": "left",
                    "path": left["path"],
                    "textWidth": 120,
                    "textHeight": 15,
                    "clippingRect": rect(0, 100, 0, 20),
                }
            ],
        }

        layout = analyze_layout_diagnostics(tree, raw)

        self.assertEqual(2, layout["actionableCount"])
        overlap = layout["overlaps"][0]
        self.assertEqual("floater_test.xml", overlap["sourceFile"])
        self.assertEqual("/Floater View/floater/right", overlap["other"]["path"])
        self.assertEqual(
            ["/Floater View", "/Floater View/floater"],
            [ancestor["path"] for ancestor in overlap["ancestors"]],
        )
        clipping = layout["textClipping"][0]
        self.assertEqual(left["local_rect"], clipping["localRect"])
        self.assertEqual("9LLTextBox", clipping["class"])


if __name__ == "__main__":
    unittest.main()
