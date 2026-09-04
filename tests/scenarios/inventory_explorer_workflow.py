"""Exercise Inventory Explorer view state, navigation, search, and holding."""

import platform
from pathlib import Path
from typing import Any

from xui_lab import Capability, Scenario, Viewport, Window
from xui_lab.errors import AssertionFailure
from xui_lab.image_comparison import compare_png

LAB_FIXTURES = "20000000-0000-4000-8000-000000000002"
KNOWN_NOTECARD = "30000000-0000-4000-8000-000000000001"
PANEL = (
    "/Floater View/floater_al_inventory_explorer/inventory_explorer_panel/"
    "inventory_explorer_layout_stack/content_layout_panel/content_layout_stack"
)
TREE_VIEW = f"{PANEL}/toolbar_layout_panel/tree_view_button"
LIST_VIEW = f"{PANEL}/toolbar_layout_panel/list_view_button"
GRID_VIEW = f"{PANEL}/toolbar_layout_panel/grid_view_button"
BACK = f"{PANEL}/toolbar_layout_panel/back_button"
FORWARD = f"{PANEL}/toolbar_layout_panel/forward_button"
UP = f"{PANEL}/toolbar_layout_panel/up_button"
SEARCH = f"{PANEL}/toolbar_layout_panel/inventory_explorer_search_editor"
STATUS = f"{PANEL}/status_layout_panel/status_text"
HOLDING_LAYOUT = f"{PANEL}/holding_tray_layout_panel"
HOLDING_TRAY = f"{HOLDING_LAYOUT}/inventory_holding_tray"
CLEAR_HOLDING = f"{HOLDING_TRAY}/clear_button"
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


def _value(window: Window, suffix: str, *, within: str) -> Any:
    matches = [
        node.get("value")
        for node in _nodes(window.query_tree())
        if isinstance(node.get("path"), str)
        and node["path"].startswith(within)
        and node["path"].endswith(f"/{suffix}")
        and node.get("visible_chain") is True
    ]
    if len(matches) != 1:
        raise AssertionFailure(
            f"visible control {suffix!r} matched {len(matches)} values: {matches}"
        )
    return matches[0]


def _model_visible(window: Window, model_id: str) -> bool:
    return any(
        node.get("model_id") == model_id and node.get("visible_chain") is True
        for node in _nodes(window.query_tree())
    )


def _path_visible(window: Window, path: str) -> bool:
    return any(
        node.get("path") == path and node.get("visible_chain") is True
        for node in _nodes(window.query_tree())
    )


def _assert_selection(window: Window, view_button: str) -> None:
    window.get_by_path(view_button).click().expect_handled()
    window.wait_for_stable()
    notecard = window.get_by_model_id(KNOWN_NOTECARD)
    notecard.expect_visible()
    notecard.expect_selected()
    window.get_by_path(f"{INSPECTOR}/details_scroll").expect_visible()
    if _value(window, "item_name", within=INSPECTOR) != "Known Notecard":
        raise AssertionFailure("view switch did not preserve the inspector selection")


def run(window: Window) -> None:
    window.wait_for_stable()

    tree_view = window.get_by_role("button", name="Tree view").resolve()
    if tree_view.path != TREE_VIEW:
        raise AssertionFailure(
            f"Tree view role locator resolved to {tree_view.path}, expected {TREE_VIEW}"
        )

    folder = window.get_by_model_id(LAB_FIXTURES)
    folder.double_click().expect_handled()
    folder.expect("open", True)

    window.get_by_model_id(KNOWN_NOTECARD).click().expect_handled()
    for view_button in (LIST_VIEW, GRID_VIEW, TREE_VIEW):
        _assert_selection(window, view_button)

    expected_details = {
        "item_name": "Known Notecard",
        "item_type": "note card",
        "item_creator": "Lab Resident (lab.resident)",
        "item_permissions": "Copy, Modify, Transfer",
    }
    for control, expected in expected_details.items():
        actual = _value(window, control, within=INSPECTOR)
        if actual != expected:
            raise AssertionFailure(
                f"inspector {control} is {actual!r}, expected {expected!r}"
            )

    window.get_by_path(LIST_VIEW).click().expect_handled()
    window.get_by_path(STATUS).expect_value("My Inventory > Lab Fixtures")
    window.get_by_path(UP).click().expect_handled()
    window.get_by_path(STATUS).expect_value("My Inventory")
    back = window.get_by_path(BACK)
    back.expect_enabled()
    back.click().expect_handled()
    window.get_by_path(STATUS).expect_value("My Inventory > Lab Fixtures")
    forward = window.get_by_path(FORWARD)
    forward.expect_enabled()
    forward.click().expect_handled()
    window.get_by_path(STATUS).expect_value("My Inventory")
    back.click().expect_handled()

    search = window.get_by_path(SEARCH)
    search.fill("No such item").expect_handled()
    if _model_visible(window, KNOWN_NOTECARD):
        raise AssertionFailure("search left a non-matching inventory item visible")
    search.fill("Known").expect_handled()
    notecard = window.get_by_model_id(KNOWN_NOTECARD)
    notecard.expect_visible()
    search.fill("").expect_handled()

    if _path_visible(window, HOLDING_LAYOUT):
        raise AssertionFailure("holding tray is visible before a drop")
    drop = notecard.drag_to(window.get_by_path(HOLDING_TRAY)).expect_handled().data
    if drop.get("accepted") is not True or drop.get("dropped") is not True:
        raise AssertionFailure(f"holding tray rejected the inventory item: {drop}")
    if not _path_visible(window, HOLDING_LAYOUT):
        raise AssertionFailure("holding tray stayed hidden after an accepted drop")
    if _value(window, "item_name", within=HOLDING_TRAY) != "Known Notecard":
        raise AssertionFailure("holding tray did not display the dropped item")
    capture = window.capture("inventory-explorer-workflow")
    baseline = (
        Path(__file__).parents[1]
        / "baselines"
        / platform.system().lower()
        / "inventory-explorer-workflow.png"
    )
    if baseline.is_file():
        compare_png(Path(capture["path"]), baseline)

    window.get_by_path(CLEAR_HOLDING).click().expect_handled()
    if _path_visible(window, HOLDING_LAYOUT):
        raise AssertionFailure("clearing the holding tray did not hide it")


SCENARIO = Scenario(
    id="inventory_explorer_workflow",
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
