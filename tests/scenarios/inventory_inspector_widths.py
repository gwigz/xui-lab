"""Keep the empty Inventory Explorer inspector text inside its clip rectangle."""

from pathlib import Path
from typing import Any

from xui_lab import Capability, Scenario, Viewport, Window
from xui_lab.errors import AssertionFailure

# The empty inspector is the panel the floater shows until a selection exists.
EMPTY_PANEL = "empty_panel"
TEXT_NAMES = ("inspector_title", "inspector_empty_message")
SIDES = ("left", "right", "top", "bottom")
# applyLayout hides the inspector below 700. 920 is the default floater width.
WIDE_WIDTHS = (920, 720)
COMPACT_WIDTHS = (520, 360)
HEIGHT = 640


def _nodes(tree: Any) -> list[dict[str, Any]]:
    if not isinstance(tree, dict):
        return []
    result = [tree]
    children = tree.get("children")
    if isinstance(children, list):
        for child in children:
            result.extend(_nodes(child))
    return result


def _node(tree: Any, name: str) -> dict[str, Any]:
    suffix = f"/{name}"
    matches = [
        node
        for node in _nodes(tree)
        if isinstance(node.get("path"), str) and node["path"].endswith(suffix)
    ]
    if len(matches) != 1:
        paths = ", ".join(str(node.get("path")) for node in matches) or "none"
        raise AssertionFailure(
            f"inspector view {name!r} matched {len(matches)} controls; matches: {paths}"
        )
    return matches[0]


def _rect(node: dict[str, Any], key: str) -> dict[str, int]:
    rect = node.get(key)
    if not isinstance(rect, dict) or any(side not in rect for side in SIDES):
        raise AssertionFailure(f"{node.get('path')} reported no {key}")
    return {side: int(rect[side]) for side in SIDES}


def _assert_unclipped(node: dict[str, Any], width: int) -> None:
    screen = _rect(node, "screen_rect")
    clipping = _rect(node, "clipping_rect")
    outside = [
        side
        for side, inside in (
            ("left", screen["left"] >= clipping["left"]),
            ("right", screen["right"] <= clipping["right"]),
            ("bottom", screen["bottom"] >= clipping["bottom"]),
            ("top", screen["top"] <= clipping["top"]),
        )
        if not inside
    ]
    if outside:
        raise AssertionFailure(
            f"{node.get('path')} leaves its clipping rectangle at width {width} "
            f"on the {', '.join(outside)} side; screen={screen} clipping={clipping}"
        )


def run(window: Window) -> None:
    window.wait_for_stable()

    for width in WIDE_WIDTHS:
        window.resize_subject(width, HEIGHT)
        window.wait_for_stable()

        tree = window.query_tree()
        empty_panel = _node(tree, EMPTY_PANEL)
        if empty_panel.get("visible_chain") is not True:
            raise AssertionFailure(
                f"the empty inspector is hidden at width {width}; "
                f"visible_chain={empty_panel.get('visible_chain')}"
            )
        for name in TEXT_NAMES:
            _assert_unclipped(_node(tree, name), width)

        window.capture(f"empty-inspector-{width}")

    for width in COMPACT_WIDTHS:
        window.resize_subject(width, HEIGHT)
        window.wait_for_stable()

        empty_panel = _node(window.query_tree(), EMPTY_PANEL)
        if empty_panel.get("visible_chain") is True:
            raise AssertionFailure(
                f"compact layout still shows the empty inspector at width {width}"
            )
        window.capture(f"empty-inspector-{width}")


SCENARIO = Scenario(
    id="inventory_inspector_widths",
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
