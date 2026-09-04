"""Classify raw LLUI layout observations into actionable diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

Rect = Mapping[str, int]

_SCROLL_CONTAINER_CLASSES = frozenset(
    {
        "LLFlatListView",
        "LLFolderView",
        "LLInventoryGallery",
        "LLScrollContainer",
        "LLScrollableContainerView",
        "LLScrollListCtrl",
    }
)
_HOST_ROOT_PATHS = frozenset({"/Floater View", "/Menu Holder"})


@dataclass(frozen=True)
class _IndexedNode:
    raw: dict[str, Any]
    ancestors: tuple[dict[str, Any], ...]


def _runtime_class(node: Mapping[str, Any]) -> str:
    return str(node.get("class", "")).lstrip("0123456789")


def _control_context(node: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "controlId": node.get("control_id", ""),
        "path": node.get("path", ""),
        "class": node.get("class", ""),
        "sourceFile": node.get("source_file", ""),
        "sourceLine": node.get("source_line", 0),
        "localRect": node.get("local_rect", {}),
        "screenRect": node.get("screen_rect", {}),
        "clippingRect": node.get("clipping_rect", {}),
    }


def _index_tree(
    tree: dict[str, Any],
) -> tuple[list[_IndexedNode], dict[str, _IndexedNode]]:
    ordered: list[_IndexedNode] = []
    by_control_id: dict[str, _IndexedNode] = {}

    def visit(node: dict[str, Any], ancestors: tuple[dict[str, Any], ...]) -> None:
        indexed = _IndexedNode(node, ancestors)
        ordered.append(indexed)
        control_id = node.get("control_id")
        if isinstance(control_id, str) and control_id:
            by_control_id[control_id] = indexed
        children = node.get("children", [])
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    visit(child, (*ancestors, node))

    visit(tree, ())
    return ordered, by_control_id


def _issue_context(indexed: _IndexedNode) -> dict[str, Any]:
    return {
        **_control_context(indexed.raw),
        "ancestors": [_control_context(node) for node in indexed.ancestors],
    }


def _rect(value: Any) -> Rect | None:
    if not isinstance(value, dict):
        return None
    sides = ("left", "right", "bottom", "top")
    if any(
        not isinstance(value.get(side), int) or isinstance(value.get(side), bool)
        for side in sides
    ):
        return None
    return value


def _negative(rectangle: Rect) -> bool:
    return (
        rectangle["right"] < rectangle["left"] or rectangle["top"] < rectangle["bottom"]
    )


def _empty(rectangle: Rect) -> bool:
    return (
        rectangle["right"] <= rectangle["left"]
        or rectangle["top"] <= rectangle["bottom"]
    )


def _outside(rectangle: Rect, clipping: Rect, *, tolerance: int = 0) -> bool:
    return (
        rectangle["left"] < clipping["left"] - tolerance
        or rectangle["right"] > clipping["right"] + tolerance
        or rectangle["bottom"] < clipping["bottom"] - tolerance
        or rectangle["top"] > clipping["top"] + tolerance
    )


def _inside_scroll_container(indexed: _IndexedNode) -> bool:
    return any(
        _runtime_class(ancestor) in _SCROLL_CONTAINER_CLASSES
        for ancestor in indexed.ancestors
    )


def _invalid_rectangles(nodes: list[_IndexedNode]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for indexed in nodes:
        if indexed.raw.get("visible_chain") is not True:
            continue
        if not indexed.raw.get("source_file"):
            continue
        for wire_name, tree_name in (
            ("localRect", "local_rect"),
            ("clippingRect", "clipping_rect"),
        ):
            rectangle = _rect(indexed.raw.get(tree_name))
            if rectangle is not None and _negative(rectangle):
                issues.append(
                    {
                        **_issue_context(indexed),
                        "rectangle": wire_name,
                        "reason": f"{wire_name} has a negative width or height",
                    }
                )
    return issues


def _outside_parent(nodes: list[_IndexedNode]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for indexed in nodes:
        if indexed.raw.get("visible_chain") is not True or not indexed.ancestors:
            continue
        if not indexed.raw.get("source_file"):
            continue
        if indexed.raw.get("path") in _HOST_ROOT_PATHS:
            continue
        if _inside_scroll_container(indexed):
            continue
        parent = indexed.ancestors[-1]
        screen = _rect(indexed.raw.get("screen_rect"))
        parent_clipping = _rect(parent.get("clipping_rect"))
        if (
            screen is None
            or parent_clipping is None
            or _empty(screen)
            or _outside(screen, parent_clipping, tolerance=1) is False
        ):
            continue
        issues.append(
            {
                **_issue_context(indexed),
                "parentControlId": parent.get("control_id", ""),
                "parentPath": parent.get("path", ""),
                "parentClippingRect": parent_clipping,
                "reason": "screenRect extends beyond the parent clipping rectangle",
            }
        )
    return issues


def _enrich_raw_issue(
    issue: Mapping[str, Any], indexed: _IndexedNode | None
) -> dict[str, Any]:
    return {
        **dict(issue),
        **(_issue_context(indexed) if indexed is not None else {}),
    }


def _overlaps(
    raw: Mapping[str, Any], by_control_id: Mapping[str, _IndexedNode]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    values = raw.get("overlaps", [])
    if not isinstance(values, list):
        return issues
    for value in values:
        if not isinstance(value, dict):
            continue
        paths = frozenset({value.get("path"), value.get("otherPath")})
        if paths == _HOST_ROOT_PATHS:
            continue
        indexed = by_control_id.get(str(value.get("controlId", "")))
        other = by_control_id.get(str(value.get("otherControlId", "")))
        enriched = _enrich_raw_issue(value, indexed)
        if other is not None:
            enriched["other"] = _control_context(other.raw)
        enriched.setdefault("reason", "visible sibling controls overlap")
        issues.append(enriched)
    return issues


def _text_clipping(
    raw: Mapping[str, Any], by_control_id: Mapping[str, _IndexedNode]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    values = raw.get("textClipping", [])
    if not isinstance(values, list):
        return issues
    for value in values:
        if not isinstance(value, dict):
            continue
        indexed = by_control_id.get(str(value.get("controlId", "")))
        clipping = _rect(value.get("clippingRect"))
        if (
            indexed is not None
            and clipping is not None
            and _inside_scroll_container(indexed)
            and (
                _empty(clipping)
                or (
                    (screen := _rect(indexed.raw.get("screen_rect"))) is not None
                    and _outside(screen, clipping)
                )
            )
        ):
            continue
        enriched = _enrich_raw_issue(value, indexed)
        enriched.setdefault("reason", "text extends beyond the clipping rectangle")
        issues.append(enriched)
    return issues


def analyze_layout_diagnostics(
    tree: dict[str, Any], raw: Mapping[str, Any]
) -> dict[str, Any]:
    """Return enriched, actionable layout findings for one production tree."""
    nodes, by_control_id = _index_tree(tree)
    overlaps = _overlaps(raw, by_control_id)
    text_clipping = _text_clipping(raw, by_control_id)
    invalid_rectangles = _invalid_rectangles(nodes)
    outside_parent = _outside_parent(nodes)
    return {
        **dict(raw),
        "overlaps": overlaps,
        "textClipping": text_clipping,
        "invalidRectangles": invalid_rectangles,
        "outsideParent": outside_parent,
        "actionableCount": sum(
            len(values)
            for values in (
                overlaps,
                text_clipping,
                invalid_rectangles,
                outside_parent,
            )
        ),
    }
