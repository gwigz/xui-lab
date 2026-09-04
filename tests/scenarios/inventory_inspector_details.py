"""Keep selected-item details flush with the Inventory Explorer inspector."""

from pathlib import Path
from typing import Any

from xui_lab import Capability, Scenario, Viewport, Window
from xui_lab.errors import AssertionFailure

LAB_FIXTURES = "20000000-0000-4000-8000-000000000002"
KNOWN_NOTECARD = "30000000-0000-4000-8000-000000000001"
INSPECTOR = (
    "/Floater View/floater_al_inventory_explorer/inventory_explorer_panel/"
    "inventory_explorer_layout_stack/inspector_layout_panel/inventory_inspector"
)
DETAILS_SCROLL = f"{INSPECTOR}/details_scroll"
DETAILS_PANEL = f"{DETAILS_SCROLL}/details_panel"
DETAILS_TITLE = f"{DETAILS_PANEL}/details_title"
PREVIEW = f"{DETAILS_PANEL}/preview_background"
ITEM_NAME = f"{DETAILS_PANEL}/item_name"
TYPE_BADGE = f"{DETAILS_PANEL}/item_type_badge"
PROPERTIES_HINT = f"{DETAILS_PANEL}/properties_hint"
VERTICAL_SCROLLBAR = f"{DETAILS_SCROLL}/scrollable vertical"
HORIZONTAL_SCROLLBAR = f"{DETAILS_SCROLL}/scrollable horizontal"
SIDES = ("left", "right", "top", "bottom")


def _nodes(tree: Any) -> list[dict[str, Any]]:
    if not isinstance(tree, dict):
        return []
    result = [tree]
    children = tree.get("children")
    if isinstance(children, list):
        for child in children:
            result.extend(_nodes(child))
    return result


def _node(tree: Any, path: str) -> dict[str, Any]:
    matches = [node for node in _nodes(tree) if node.get("path") == path]
    if len(matches) != 1:
        raise AssertionFailure(f"{path} matched {len(matches)} controls")
    return matches[0]


def _rect(node: dict[str, Any], key: str) -> dict[str, int]:
    value = node.get(key)
    if not isinstance(value, dict) or any(side not in value for side in SIDES):
        raise AssertionFailure(f"{node.get('path')} reported no {key}")
    return {side: int(value[side]) for side in SIDES}


def _assert_details_width(tree: Any) -> None:
    details_scroll = _node(tree, DETAILS_SCROLL)
    details_panel = _node(tree, DETAILS_PANEL)
    vertical_scrollbar = _node(tree, VERTICAL_SCROLLBAR)
    horizontal_scrollbar = _node(tree, HORIZONTAL_SCROLLBAR)
    scroll_clip = _rect(details_scroll, "clipping_rect")
    panel_rect = _rect(details_panel, "screen_rect")
    expected_right = scroll_clip["right"]
    if vertical_scrollbar.get("visible_chain") is True:
        expected_right = _rect(vertical_scrollbar, "screen_rect")["left"]

    if (
        panel_rect["left"] != scroll_clip["left"]
        or panel_rect["right"] != expected_right
    ):
        raise AssertionFailure(
            "details panel does not fill the scroll viewport; "
            f"panel={panel_rect}, scroll clipping={scroll_clip}, "
            f"expected right={expected_right}"
        )
    if horizontal_scrollbar.get("visible_chain") is True:
        raise AssertionFailure("details panel triggered a horizontal scrollbar")


def _assert_details_hierarchy(tree: Any) -> None:
    preview = _rect(_node(tree, PREVIEW), "screen_rect")
    item_name = _rect(_node(tree, ITEM_NAME), "screen_rect")
    type_badge = _rect(_node(tree, TYPE_BADGE), "screen_rect")
    if preview["right"] - preview["left"] < 150:
        raise AssertionFailure(f"inspector preview is too small: {preview}")
    if item_name["top"] > preview["bottom"]:
        raise AssertionFailure(
            f"item name is not below the preview: preview={preview}, name={item_name}"
        )
    if type_badge["top"] > item_name["bottom"]:
        raise AssertionFailure(
            f"type badge is not below the item name: name={item_name}, badge={type_badge}"
        )


def run(window: Window) -> None:
    window.wait_for_stable()
    folder = window.get_by_model_id(LAB_FIXTURES)
    folder.double_click().expect_handled()
    window.get_by_model_id(KNOWN_NOTECARD).click().expect_handled()
    window.wait_for_stable()

    tree = window.query_tree()
    details_scroll = _node(tree, DETAILS_SCROLL)
    if details_scroll.get("visible_chain") is not True:
        raise AssertionFailure("selected-item details did not become visible")
    _assert_details_width(tree)
    _assert_details_hierarchy(tree)

    obsolete = (PROPERTIES_HINT, DETAILS_TITLE)
    if any(node.get("path") in obsolete for node in _nodes(tree)):
        raise AssertionFailure("obsolete inspector copy remains")

    window.expect_no_layout_diagnostics(path_prefix=INSPECTOR)
    window.capture("inventory-inspector-details")

    window.resize_subject(1024, 360)
    window.wait_for_stable()
    _assert_details_width(window.query_tree())
    window.expect_no_layout_diagnostics(path_prefix=INSPECTOR)

    window.resize_subject(1024, 700)
    window.wait_for_stable()
    window.expect_no_layout_diagnostics(path_prefix=INSPECTOR)

    window.resize_subject(760, 700)
    window.wait_for_stable()
    _assert_details_width(window.query_tree())
    _assert_details_hierarchy(window.query_tree())
    window.expect_no_layout_diagnostics(path_prefix=INSPECTOR)


SCENARIO = Scenario(
    id="inventory_inspector_details",
    fork="alchemy",
    subject="inventory_explorer",
    viewport=Viewport(1024, 700, 1.0),
    capabilities=frozenset(
        {
            Capability("input"),
            Capability("inspection"),
            Capability("inventory_model"),
            Capability("agent_identity"),
            Capability("menus"),
        }
    ),
    fixture=Path("fixtures/inventory-explorer.json"),
    run=run,
)
