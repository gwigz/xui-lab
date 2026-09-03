"""Apply one-shot CLI commands to an open Window."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

from .api import Window
from .contracts import (
    SCHEMA_VERSION,
    CaptureCliCommand,
    ClickCliCommand,
    DiagnosticsCliCommand,
    DragByCliCommand,
    DragToCliCommand,
    FillCliCommand,
    GetCliCommand,
    PickCliCommand,
    PressCliCommand,
    ReloadCliCommand,
    ResizeSubjectCliCommand,
    ResizeViewportCliCommand,
    ResultRecord,
    ScrollCliCommand,
    SessionCloseCliCommand,
    TreeCliCommand,
)
from .errors import InputError
from .io import write_json
from .operations import Selector
from .selectors import (
    excerpt_node,
    project_fields,
    rank_locator,
    require_unique,
    tree_nodes,
)

INCLUDE_TREE_WARNING = (
    "warning: --include-tree inlines the full production UI tree and can be large"
)


def parse_fields(value: str | None) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    fields = tuple(part.strip() for part in value.split(",") if part.strip())
    if not fields:
        raise InputError("--fields must name at least one field")
    return fields


def selector_from_command(command: Any) -> Selector:
    from .operations import (
        control_id_selector,
        label_selector,
        model_id_selector,
        path_selector,
        placeholder_selector,
        role_selector,
        text_selector,
    )

    if command.control_id is not None:
        return control_id_selector(command.control_id)
    if command.model_id is not None:
        return model_id_selector(command.model_id)
    if command.path is not None:
        return path_selector(command.path)
    if command.role is not None:
        return role_selector(command.role, command.name)
    if command.label is not None:
        return label_selector(command.label)
    if command.placeholder is not None:
        return placeholder_selector(command.placeholder)
    if command.text is not None:
        return text_selector(command.text)
    raise InputError("exactly one selector flag is required")


def _result(command: Any, data: dict[str, Any]) -> dict[str, Any]:
    return ResultRecord(
        schemaVersion=SCHEMA_VERSION,
        type="result",
        requestId=command.request_id,
        operation=command.command,
        data=data,
    ).model_dump(mode="json", by_alias=True)


def _write_tree_artifact(window: Window, tree: dict[str, Any]) -> dict[str, Any]:
    path = window.artifact_dir / "ui-tree.json"
    write_json(path, tree)
    data = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def apply_window_command(window: Window, command: Any) -> dict[str, Any]:
    if isinstance(command, SessionCloseCliCommand):
        return _result(
            command,
            {"sessionId": command.session_id, "terminated": True, "closed": True},
        )
    if isinstance(command, TreeCliCommand):
        tree = window.query_tree()
        artifact = _write_tree_artifact(window, tree)
        node = tree
        if command.path is not None:
            matches = [
                item for item in tree_nodes(tree) if item.get("path") == command.path
            ]
            if len(matches) != 1:
                raise InputError(f"tree path matched {len(matches)} nodes")
            node = matches[0]
        payload: dict[str, Any] = {"treeArtifact": artifact}
        if command.include_tree:
            print(INCLUDE_TREE_WARNING, file=sys.stderr)
            payload["tree"] = node
        else:
            payload["tree"] = excerpt_node(node)
        return _result(command, project_fields(payload, parse_fields(command.fields)))
    if isinstance(command, GetCliCommand):
        tree = window.query_tree()
        selector = selector_from_command(command)
        node = require_unique(tree, selector)
        ranked = rank_locator(node, tree)
        payload = {
            "control": excerpt_node(node, children=False),
            "locator": {
                "python": ranked.python,
                "kind": ranked.kind,
                "matchCount": ranked.match_count,
                "signals": list(ranked.signals),
                "fallbackReason": ranked.fallback_reason,
            },
        }
        if command.include_tree:
            print(INCLUDE_TREE_WARNING, file=sys.stderr)
            payload["control"] = node
        return _result(command, project_fields(payload, parse_fields(command.fields)))
    if isinstance(command, PickCliCommand):
        control = window.pick(command.x, command.y)
        return _result(command, {"control": excerpt_node(control.info, children=False)})
    if isinstance(command, ClickCliCommand):
        locator = window.locator(selector_from_command(command))
        result = locator.click()
        return _result(command, result.data)
    if isinstance(command, FillCliCommand):
        locator = window.locator(selector_from_command(command))
        result = locator.fill(command.text_value)
        return _result(command, result.data)
    if isinstance(command, PressCliCommand):
        locator = window.locator(selector_from_command(command))
        result = locator.press(command.key, modifiers=tuple(command.modifiers))
        return _result(command, result.data)
    if isinstance(command, ScrollCliCommand):
        locator = window.locator(selector_from_command(command))
        result = locator.scroll(command.clicks)
        return _result(command, result.data)
    if isinstance(command, DragByCliCommand):
        locator = window.locator(selector_from_command(command))
        result = locator.drag_by(dx=command.dx, dy=command.dy)
        return _result(command, result.data)
    if isinstance(command, DragToCliCommand):
        source = window.locator(selector_from_command(command))
        target = window.get_by_control_id(command.target_control_id)
        result = source.drag_to(target)
        return _result(command, result.data)
    if isinstance(command, ResizeViewportCliCommand):
        data = window.resize_viewport(
            command.width, command.height, ui_scale=command.ui_scale
        )
        return _result(command, data)
    if isinstance(command, ResizeSubjectCliCommand):
        data = window.resize_subject(command.width, command.height)
        return _result(command, data)
    if isinstance(command, CaptureCliCommand):
        data = window.capture(command.name or "capture")
        path = data.get("path")
        if isinstance(path, str):
            file_path = Path(path)
            if file_path.is_file():
                blob = file_path.read_bytes()
                data = {
                    **data,
                    "size": len(blob),
                    "sha256": hashlib.sha256(blob).hexdigest(),
                }
        return _result(command, data)
    if isinstance(command, ReloadCliCommand):
        return _result(command, window.reload())
    if isinstance(command, DiagnosticsCliCommand):
        return _result(command, window.diagnostics())
    raise InputError(f"command cannot run on a session: {command.command}")
