"""Upload from Inventory Explorer does not open a file dialog or add items."""

from pathlib import Path
from typing import Any

from xui_lab import Capability, Scenario, Viewport, Window
from xui_lab.errors import AssertionFailure

LAB_FIXTURES = "20000000-0000-4000-8000-000000000002"
KNOWN_NOTECARD = "30000000-0000-4000-8000-000000000001"


def _nodes(tree: Any) -> list[dict[str, Any]]:
    if not isinstance(tree, dict):
        return []
    result = [tree]
    children = tree.get("children")
    if isinstance(children, list):
        for child in children:
            result.extend(_nodes(child))
    return result


def _model_ids(tree: Any) -> list[str]:
    return sorted(
        node["model_id"]
        for node in _nodes(tree)
        if isinstance(node.get("model_id"), str) and node["model_id"]
    )


def _floater_names(tree: Any) -> list[str]:
    names = []
    for node in _nodes(tree):
        path = node.get("path")
        if not isinstance(path, str) or not path.startswith("/Floater View/"):
            continue
        rest = path[len("/Floater View/") :]
        if rest and "/" not in rest:
            names.append(rest)
    return sorted(names)


def _click_menu(window: Window, label: str) -> None:
    entry = window.expect_menu_entry(label)
    target = (
        window.get_by_control_id(entry.control_id)
        if entry.control_id
        else window.get_by_path(entry.path)
    )
    target.click().expect_handled()


def run(window: Window) -> None:
    window.wait_for_stable()

    folder = window.get_by_model_id(LAB_FIXTURES)
    folder.expect_visible()
    folder.double_click().expect_handled()
    folder.expect("open", True)
    window.get_by_model_id(KNOWN_NOTECARD).expect_visible()

    before_ids = _model_ids(window.query_tree())
    before_floaters = _floater_names(window.query_tree())

    folder.right_click().expect_handled()
    window.expect_menu_visible(True)
    _click_menu(window, "Upload to folder")
    _click_menu(window, "Image...")

    window.get_by_model_id(KNOWN_NOTECARD).expect_visible()
    after_ids = _model_ids(window.query_tree())
    after_floaters = _floater_names(window.query_tree())
    if after_ids != before_ids:
        raise AssertionFailure(
            f"upload changed inventory model ids: {before_ids} -> {after_ids}"
        )
    if after_floaters != before_floaters:
        raise AssertionFailure(
            f"upload opened extra floaters: {before_floaters} -> {after_floaters}"
        )
    window.capture("file-upload", highlight=folder)


SCENARIO = Scenario(
    id="file_upload",
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
