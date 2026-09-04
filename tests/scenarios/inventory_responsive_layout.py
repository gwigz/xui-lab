"""Keep Inventory Explorer navigation usable across responsive states."""

from pathlib import Path
from typing import Any

from xui_lab import Capability, Scenario, Viewport, Window
from xui_lab.errors import AssertionFailure

LAYOUT = (
    "/Floater View/floater_al_inventory_explorer/inventory_explorer_panel/"
    "inventory_explorer_layout_stack"
)
RAIL = f"{LAYOUT}/collections_rail_layout_panel"
CONTENT = f"{LAYOUT}/content_layout_panel"
INSPECTOR = f"{LAYOUT}/inspector_layout_panel"
RECENT_BUTTON = f"{RAIL}/recent_collection_button"
RECENT_ICON = f"{RAIL}/recent_collection_icon"
RECENT_LABEL = f"{RAIL}/recent_collection_label"
RECENT_VIEW = (
    f"{LAYOUT}/content_layout_panel/content_layout_stack/"
    "active_view_layout_panel/recent_collection_view"
)
COMPACT_WIDTH = 360
WIDE_WIDTH = 800
LARGE_WIDTH = 1024
COMPACT_HEIGHT = 580
WIDE_HEIGHT = 640
LARGE_HEIGHT = 700


def _nodes(tree: Any) -> list[dict[str, Any]]:
    if not isinstance(tree, dict):
        return []
    result = [tree]
    children = tree.get("children")
    if isinstance(children, list):
        for child in children:
            result.extend(_nodes(child))
    return result


def _node(window: Window, path: str) -> dict[str, Any]:
    matches = [node for node in _nodes(window.query_tree()) if node.get("path") == path]
    if len(matches) != 1:
        raise AssertionFailure(f"{path} matched {len(matches)} controls")
    return matches[0]


def _expect_visible(window: Window, path: str, expected: bool) -> None:
    actual = _node(window, path).get("visible_chain") is True
    if actual != expected:
        raise AssertionFailure(f"{path} visibility is {actual}, expected {expected}")


def _expect_width(window: Window, path: str, expected: int) -> None:
    screen_rect = _node(window, path).get("screen_rect")
    if not isinstance(screen_rect, dict):
        raise AssertionFailure(f"{path} has no screen rectangle")
    actual = int(screen_rect["right"]) - int(screen_rect["left"])
    if actual != expected:
        raise AssertionFailure(f"{path} width is {actual}, expected {expected}")


def _screen_rect(node: dict[str, Any]) -> dict[str, int]:
    value = node.get("screen_rect")
    if not isinstance(value, dict):
        raise AssertionFailure(f"{node.get('path')} has no screen rectangle")
    return {side: int(value[side]) for side in ("left", "right", "top", "bottom")}


def _expect_subtle_splitters(window: Window) -> None:
    tree = window.query_tree()
    rail = _screen_rect(next(node for node in _nodes(tree) if node.get("path") == RAIL))
    content = _screen_rect(
        next(node for node in _nodes(tree) if node.get("path") == CONTENT)
    )
    inspector = _screen_rect(
        next(node for node in _nodes(tree) if node.get("path") == INSPECTOR)
    )
    gaps = (content["left"] - rail["right"], inspector["left"] - content["right"])
    if gaps != (1, 1):
        raise AssertionFailure(f"splitter gaps are {gaps}, expected (1, 1)")

    grip_images = [
        node
        for node in _nodes(tree)
        if isinstance(node.get("path"), str)
        and node["path"].startswith(f"{LAYOUT}/resize/")
        and node["path"].endswith("/resize_handle_image")
        and node.get("visible_chain") is True
    ]
    if grip_images:
        raise AssertionFailure("splitter grip arrows remain visible")

    resize_bars = [
        _screen_rect(node)
        for node in _nodes(tree)
        if node.get("path") == f"{LAYOUT}/resize" and node.get("visible_chain") is True
    ]
    widths = [rect["right"] - rect["left"] for rect in resize_bars]
    if len(widths) != 2 or any(width < 9 for width in widths):
        raise AssertionFailure(f"splitter resize targets have widths {widths}")


def run(window: Window) -> None:
    window.resize_subject(COMPACT_WIDTH, COMPACT_HEIGHT)
    window.wait_for_stable()

    _expect_width(window, RAIL, 46)
    _expect_visible(window, RECENT_ICON, True)
    _expect_visible(window, RECENT_LABEL, False)
    _expect_visible(window, INSPECTOR, False)

    window.get_by_path(RECENT_BUTTON).click().expect_handled()
    window.wait_for_stable()
    _expect_visible(window, RECENT_VIEW, True)
    window.expect_no_layout_diagnostics(path_prefix=RAIL)
    window.capture("inventory-compact-rail")

    window.resize_subject(WIDE_WIDTH, WIDE_HEIGHT)
    window.wait_for_stable()

    _expect_width(window, RAIL, 188)
    _expect_visible(window, RECENT_ICON, True)
    _expect_visible(window, RECENT_LABEL, True)
    _expect_visible(window, INSPECTOR, True)
    _expect_visible(window, RECENT_VIEW, True)
    _expect_subtle_splitters(window)
    window.expect_no_layout_diagnostics(path_prefix=RAIL)
    window.capture("inventory-wide-rail")

    window.resize_subject(LARGE_WIDTH, LARGE_HEIGHT)
    window.wait_for_stable()
    _expect_width(window, RAIL, 188)
    _expect_subtle_splitters(window)
    window.expect_no_layout_diagnostics(path_prefix=RAIL)
    window.capture("inventory-large-rail")


SCENARIO = Scenario(
    id="inventory_responsive_layout",
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
    fixture=Path("fixtures/inventory-responsive-layout.json"),
    run=run,
)
