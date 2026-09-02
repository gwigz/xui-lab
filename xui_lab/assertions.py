"""Structural assertions shared by the Python API and JSON scenarios."""

from __future__ import annotations

from typing import Any

from .domain import AssertionStep, Comparison
from .errors import AssertionFailure


MISSING = object()


def resolve_pointer(value: Any, pointer: str) -> Any:
    if not pointer:
        return value
    current = value
    for encoded in pointer.removeprefix("/").split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdecimal() and int(token) < len(current):
            current = current[int(token)]
        else:
            return MISSING
    return current


def check_observation(label: str, value: Any, pointer: str, comparison: Comparison, expected: Any) -> None:
    actual = resolve_pointer(value, pointer)
    location = f"{label}{pointer}"
    if comparison is Comparison.EXISTS:
        if actual is MISSING:
            raise AssertionFailure(f"{location} does not exist")
        return
    if actual is MISSING:
        raise AssertionFailure(f"{location} does not exist")
    if comparison is Comparison.EQUALS and actual != expected:
        raise AssertionFailure(f"{location} expected {expected!r}, got {actual!r}")
    if comparison is Comparison.CONTAINS:
        try:
            contained = expected in actual
        except TypeError as error:
            raise AssertionFailure(f"{location} cannot be tested for containment") from error
        if not contained:
            raise AssertionFailure(f"{location} does not contain {expected!r}")


def check_assertion(step: AssertionStep, saved: dict[str, Any]) -> None:
    if step.source not in saved:
        raise AssertionFailure(f"assertion source was not saved: {step.source}")
    check_observation(step.source, saved[step.source], step.pointer, step.comparison, step.expected)
