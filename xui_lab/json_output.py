"""Filter CLI JSON documents with the jq language."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import jq  # type: ignore[import-not-found]

from .errors import InputError


def compile_jq(expression: str) -> Any:
    try:
        return jq.compile(expression)
    except ValueError as error:
        raise InputError(f"invalid --jq expression: {error}") from error


def format_jq_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"))


def render_json(payload: Mapping[str, Any], expression: str | None) -> str:
    if expression is None:
        return json.dumps(dict(payload), separators=(",", ":"))
    try:
        values = compile_jq(expression).input_value(dict(payload)).all()
    except ValueError as error:
        raise InputError(f"--jq failed: {error}") from error
    return "\n".join(format_jq_value(value) for value in values)


def emit_json_document(
    payload: Mapping[str, Any], expression: str | None = None
) -> None:
    if payload.get("type") == "error":
        expression = None
    text = render_json(payload, expression)
    if text:
        print(text)
