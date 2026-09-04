"""Exercise the Inventory Explorer's deterministic visual fixture."""

from pathlib import Path
from typing import Any

from xui_lab import Capability, Scenario, Viewport, Window
from xui_lab.errors import AssertionFailure

LAB_FIXTURES = "20000000-0000-4000-8000-000000000002"
VISUAL_SAMPLES = "20000000-0000-4000-8000-000000000003"
CLOTHING = "20000000-0000-4000-8000-000000000004"
ASSETS = "20000000-0000-4000-8000-000000000005"
NESTED = "20000000-0000-4000-8000-000000000006"
ARCHIVE = "20000000-0000-4000-8000-000000000007"
FAVORITE_LANDMARK = "30000000-0000-4000-8000-000000000002"
WORN_JACKET = "30000000-0000-4000-8000-000000000003"
FIRST_ARCHIVE_ITEM = "30000000-0000-4000-8000-000000000012"
LAST_ARCHIVE_ITEM = "30000000-0000-4000-8000-000000000043"
LONG_ITEM = "30000000-0000-4000-8000-000000000011"
LONG_NAME = "WWWWWWWW Wide inventory item name for truncation testing WWWWWW"
PANEL = (
    "/Floater View/floater_al_inventory_explorer/inventory_explorer_panel/"
    "inventory_explorer_layout_stack/content_layout_panel/content_layout_stack"
)
LIST_VIEW = f"{PANEL}/toolbar_layout_panel/list_view_button"
GRID_VIEW = f"{PANEL}/toolbar_layout_panel/grid_view_button"
UP = f"{PANEL}/toolbar_layout_panel/up_button"
LIST_SCROLL = f"{PANEL}/active_view_layout_panel/all_items_list/Inventory Scroller"
INSPECTOR = (
    "/Floater View/floater_al_inventory_explorer/inventory_explorer_panel/"
    "inventory_explorer_layout_stack/inspector_layout_panel/inventory_inspector"
)


def _nodes(tree: Any) -> list[dict[str, Any]]:
    if not isinstance(tree, dict):
        return []
    result = [tree]
    children = tree.get("children")
    if isinstance(children, list):
        for child in children:
            result.extend(_nodes(child))
    return result


def _visible_model_node(window: Window, model_id: str) -> dict[str, Any] | None:
    matches = [
        node
        for node in _nodes(window.query_tree())
        if node.get("model_id") == model_id
        and node.get("visible_chain") is True
        and isinstance(node.get("clipping_rect"), dict)
        and node["clipping_rect"].get("left", 0) < node["clipping_rect"].get("right", 0)
        and node["clipping_rect"].get("bottom", 0) < node["clipping_rect"].get("top", 0)
    ]
    if len(matches) > 1:
        raise AssertionFailure(
            f"model id {model_id} has {len(matches)} visible controls"
        )
    return matches[0] if matches else None


def _inspector_value(window: Window, suffix: str) -> Any:
    matches = [
        node.get("value")
        for node in _nodes(window.query_tree())
        if isinstance(node.get("path"), str)
        and node["path"].startswith(INSPECTOR)
        and node["path"].endswith(f"/{suffix}")
        and node.get("visible_chain") is True
    ]
    if len(matches) != 1:
        raise AssertionFailure(f"inspector control {suffix!r} matched {matches}")
    return matches[0]


def _open(window: Window, model_id: str) -> None:
    window.get_by_model_id(model_id).double_click().expect_handled()
    window.wait_for_stable()


def _up(window: Window) -> None:
    window.get_by_path(UP).click().expect_handled()
    window.wait_for_stable()


def run(window: Window) -> None:
    window.wait_for_stable()
    _open(window, LAB_FIXTURES)
    window.get_by_path(LIST_VIEW).click().expect_handled()
    window.wait_for_stable()
    _open(window, VISUAL_SAMPLES)
    _open(window, ASSETS)

    window.get_by_model_id(FAVORITE_LANDMARK).click().expect_handled()
    if _inspector_value(window, "item_state") != "Favorite":
        raise AssertionFailure("favorite fixture item did not reach the inspector")

    _up(window)
    _open(window, CLOTHING)
    window.get_by_path(GRID_VIEW).click().expect_handled()
    window.wait_for_stable()
    worn = _visible_model_node(window, WORN_JACKET)
    if worn is None:
        raise AssertionFailure("worn fixture item is missing from grid view")
    worn_labels = [
        node
        for node in _nodes(worn)
        if isinstance(node.get("path"), str)
        and node["path"].endswith("/item_name")
        and node.get("visible_chain") is True
        and node.get("value") == "Worn Indigo Field Jacket (worn)"
    ]
    if len(worn_labels) != 1:
        raise AssertionFailure("worn fixture item did not show its grid state")

    window.get_by_path(LIST_VIEW).click().expect_handled()
    window.wait_for_stable()
    _up(window)
    _open(window, NESTED)
    long_item = _visible_model_node(window, LONG_ITEM)
    if long_item is None or long_item.get("tooltip") != LONG_NAME:
        raise AssertionFailure("long fixture label lost its full tooltip")
    _open(window, ARCHIVE)

    window.get_by_path(GRID_VIEW).click().expect_handled()
    window.wait_for_stable()
    first_grid_item = _visible_model_node(window, FIRST_ARCHIVE_ITEM)
    if first_grid_item is None:
        raise AssertionFailure("archive fixture did not populate grid view")
    fallback = [
        node
        for node in _nodes(first_grid_item)
        if isinstance(node.get("path"), str)
        and node["path"].endswith("/preview_thumbnail")
        and node.get("visible_chain") is True
    ]
    if len(fallback) != 1:
        raise AssertionFailure("item without a thumbnail did not show fallback artwork")

    window.get_by_path(LIST_VIEW).click().expect_handled()
    window.wait_for_stable()
    if _visible_model_node(window, FIRST_ARCHIVE_ITEM) is None:
        raise AssertionFailure("first archive row is not visible at the top boundary")
    if _visible_model_node(window, LAST_ARCHIVE_ITEM) is not None:
        raise AssertionFailure("last archive row is visible before scrolling")
    window.get_by_path(LIST_SCROLL).scroll(30).expect_handled()
    if _visible_model_node(window, LAST_ARCHIVE_ITEM) is None:
        raise AssertionFailure("last archive row is not visible after scrolling")
    if _visible_model_node(window, FIRST_ARCHIVE_ITEM) is not None:
        raise AssertionFailure("first archive row stayed visible after scrolling")

    window.capture("inventory-visual-fixture")


SCENARIO = Scenario(
    id="inventory_visual_fixture",
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
