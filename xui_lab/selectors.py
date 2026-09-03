"""User-visible locators and selector ranking from the production tree."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import (
    ControlIdSelectorContract as ControlIdSelector,
)
from .contracts import (
    LabelSelectorContract as LabelSelector,
)
from .contracts import (
    ModelIdSelectorContract as ModelIdSelector,
)
from .contracts import (
    PathSelectorContract as PathSelector,
)
from .contracts import (
    PlaceholderSelectorContract as PlaceholderSelector,
)
from .contracts import (
    RoleSelectorContract as RoleSelector,
)
from .contracts import (
    Selector,
)
from .contracts import (
    TextSelectorContract as TextSelector,
)
from .errors import AssertionFailure, InputError
from .operations import (
    control_id_selector,
    label_selector,
    model_id_selector,
    path_selector,
    placeholder_selector,
    role_selector,
    text_selector,
)

CLASS_ROLES: dict[str, str] = {
    "LLButton": "button",
    "LLCheckBoxCtrl": "checkbox",
    "LLRadioCtrl": "radio",
    "LLLineEditor": "textbox",
    "LLTextEditor": "textbox",
    "LLTextBox": "label",
    "LLComboBox": "combobox",
    "LLSpinCtrl": "spinbutton",
    "LLSliderCtrl": "slider",
    "LLScrollListCtrl": "listbox",
    "LLTabContainer": "tablist",
    "LLMenuItemGL": "menuitem",
    "LLResizeHandle": "button",
    "LLPanel": "panel",
    "LLFloater": "dialog",
}

EXCERPT_KEYS = (
    "control_id",
    "path",
    "class",
    "label",
    "value",
    "placeholder",
    "model_id",
    "visible",
    "visible_chain",
    "enabled",
    "enabled_chain",
    "keyboard_focus",
    "rect",
    "screen_rect",
    "local_rect",
    "clipping_rect",
)


@dataclass(frozen=True)
class RankedLocator:
    selector: Selector
    python: str
    kind: str
    match_count: int
    signals: tuple[str, ...]
    fallback_reason: str | None


def ranked_locator_record(ranked: RankedLocator) -> dict[str, Any]:
    return {
        "selector": ranked.selector.model_dump(mode="json", by_alias=True),
        "python": ranked.python,
        "kind": ranked.kind,
        "matchCount": ranked.match_count,
        "signals": list(ranked.signals),
        "fallbackReason": ranked.fallback_reason,
    }


def explain_ranked_locator(ranked: RankedLocator, *, subject: str = "locator") -> str:
    signals = ", ".join(ranked.signals)
    fallback = ranked.fallback_reason or "none"
    return (
        f"# {subject}: signals={signals}; matches={ranked.match_count}; "
        f"fallback={fallback}"
    )


def tree_nodes(tree: Any) -> list[dict[str, Any]]:
    if not isinstance(tree, dict):
        return []
    nodes = [tree]
    children = tree.get("children", [])
    if isinstance(children, list):
        for child in children:
            nodes.extend(tree_nodes(child))
    return nodes


def node_role(node: dict[str, Any]) -> str | None:
    runtime_class = node.get("class")
    if not isinstance(runtime_class, str) or not runtime_class:
        return None
    mapped = CLASS_ROLES.get(runtime_class)
    if mapped is not None:
        return mapped
    name = runtime_class[2:] if runtime_class.startswith("LL") else runtime_class
    return name.lower() if name else None


def node_label(node: dict[str, Any]) -> str | None:
    label = node.get("label")
    return label if isinstance(label, str) and label else None


def node_placeholder(node: dict[str, Any]) -> str | None:
    placeholder = node.get("placeholder")
    return placeholder if isinstance(placeholder, str) and placeholder else None


def node_text(node: dict[str, Any]) -> str | None:
    label = node_label(node)
    if label is not None:
        return label
    value = node.get("value")
    return value if isinstance(value, str) and value else None


def is_visible(node: dict[str, Any]) -> bool:
    return node.get("visible_chain") is not False


def is_actionable(node: dict[str, Any]) -> bool:
    return is_visible(node) and node.get("enabled_chain") is not False


def wire_selector(node: dict[str, Any]) -> Selector:
    control_id = node.get("control_id")
    if isinstance(control_id, str) and control_id:
        return control_id_selector(control_id)
    path = node.get("path")
    if isinstance(path, str) and path.startswith("/"):
        return path_selector(path)
    raise AssertionFailure("matched control has no control id or path")


def _visible_nodes(tree: Any) -> list[dict[str, Any]]:
    return [node for node in tree_nodes(tree) if is_visible(node)]


def match_nodes(
    tree: Any, selector: Selector, *, actionable: bool = False
) -> list[dict[str, Any]]:
    nodes = _visible_nodes(tree)
    if actionable:
        nodes = [node for node in nodes if is_actionable(node)]
    if isinstance(selector, PathSelector):
        return [node for node in nodes if node.get("path") == selector.path]
    if isinstance(selector, ControlIdSelector):
        return [node for node in nodes if node.get("control_id") == selector.control_id]
    if isinstance(selector, ModelIdSelector):
        return [node for node in nodes if node.get("model_id") == selector.model_id]
    if isinstance(selector, RoleSelector):
        matches = [node for node in nodes if node_role(node) == selector.role]
        if selector.name is not None:
            matches = [node for node in matches if node_label(node) == selector.name]
        return matches
    if isinstance(selector, LabelSelector):
        return [node for node in nodes if node_label(node) == selector.label]
    if isinstance(selector, PlaceholderSelector):
        return [
            node for node in nodes if node_placeholder(node) == selector.placeholder
        ]
    if isinstance(selector, TextSelector):
        return [node for node in nodes if node_text(node) == selector.text]
    raise InputError(f"unsupported selector: {selector!r}")


def require_unique(
    tree: Any, selector: Selector, *, actionable: bool = False
) -> dict[str, Any]:
    matches = match_nodes(tree, selector, actionable=actionable)
    if len(matches) == 1:
        return matches[0]
    descriptions = []
    for match in matches:
        path = match.get("path", "<unknown path>")
        runtime_class = match.get("class", "<unknown class>")
        source_file = match.get("source_file", "<unknown source>")
        source_line = match.get("source_line", 0)
        descriptions.append(f"{path} ({runtime_class}, {source_file}:{source_line})")
    detail = "; ".join(descriptions) if descriptions else "none"
    raise AssertionFailure(
        f"locator for {selector.describe()} resolved to {len(matches)} controls; matches: {detail}"
    )


def _count(tree: Any, selector: Selector) -> int:
    return len(match_nodes(tree, selector))


def rank_locator(node: dict[str, Any], tree: Any) -> RankedLocator:
    role = node_role(node)
    label = node_label(node)
    placeholder = node_placeholder(node)
    text = node_text(node)
    model_id = node.get("model_id")
    control_id = node.get("control_id")
    path = node.get("path")

    if role is not None and label is not None:
        selector: Selector = role_selector(role, label)
        count = _count(tree, selector)
        if count == 1:
            return RankedLocator(
                selector=selector,
                python=f"window.get_by_role({role!r}, name={label!r})",
                kind="role",
                match_count=1,
                signals=("role", "name"),
                fallback_reason=None,
            )
    if label is not None:
        selector = label_selector(label)
        count = _count(tree, selector)
        if count == 1:
            return RankedLocator(
                selector=selector,
                python=f"window.get_by_label({label!r})",
                kind="label",
                match_count=1,
                signals=("label",),
                fallback_reason=None,
            )
    if placeholder is not None:
        selector = placeholder_selector(placeholder)
        count = _count(tree, selector)
        if count == 1:
            return RankedLocator(
                selector=selector,
                python=f"window.get_by_placeholder({placeholder!r})",
                kind="placeholder",
                match_count=1,
                signals=("placeholder",),
                fallback_reason=None,
            )
    if text is not None:
        selector = text_selector(text)
        count = _count(tree, selector)
        if count == 1:
            return RankedLocator(
                selector=selector,
                python=f"window.get_by_text({text!r})",
                kind="text",
                match_count=1,
                signals=("text",),
                fallback_reason=None,
            )
    if isinstance(model_id, str) and model_id:
        selector = model_id_selector(model_id)
        count = _count(tree, selector)
        if count == 1:
            return RankedLocator(
                selector=selector,
                python=f"window.get_by_model_id({model_id!r})",
                kind="modelId",
                match_count=1,
                signals=("modelId",),
                fallback_reason="no unique user-visible name",
            )
    if isinstance(control_id, str) and control_id:
        return RankedLocator(
            selector=control_id_selector(control_id),
            python=f"window.get_by_control_id({control_id!r})",
            kind="controlId",
            match_count=_count(tree, control_id_selector(control_id)),
            signals=("controlId",),
            fallback_reason="no unique user-visible name",
        )
    if isinstance(path, str) and path.startswith("/"):
        return RankedLocator(
            selector=path_selector(path),
            python=f"window.get_by_path({path!r})",
            kind="path",
            match_count=_count(tree, path_selector(path)),
            signals=("path",),
            fallback_reason="path used as provenance fallback",
        )
    raise AssertionFailure("control has no rankable selector")


def excerpt_node(node: dict[str, Any], *, children: bool = True) -> dict[str, Any]:
    excerpt = {key: node[key] for key in EXCERPT_KEYS if key in node}
    if children:
        raw_children = node.get("children")
        if isinstance(raw_children, list):
            excerpt["children"] = [
                excerpt_node(child, children=False)
                for child in raw_children
                if isinstance(child, dict)
            ]
    return excerpt


def project_fields(value: Any, fields: tuple[str, ...]) -> Any:
    if not fields:
        return value
    if len(fields) == 1:
        return _field_value(value, fields[0])
    return {field: _field_value(value, field) for field in fields}


def _field_value(value: Any, field: str) -> Any:
    current = value
    for part in field.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current
