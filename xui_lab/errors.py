"""Errors that may safely cross the command-line boundary."""

from collections.abc import Sequence
from typing import Any

SUMMARY_DETAILS = 2


class XUILabError(Exception):
    """A user-facing xui-lab failure."""


class InputError(XUILabError):
    """A manifest, fixture, Python scenario, or command is invalid."""


def detail_summary(details: Sequence[str]) -> str:
    """Join the first problems found in a rejected document."""
    if not details:
        return ""
    summary = "; ".join(details[:SUMMARY_DETAILS])
    hidden = len(details) - SUMMARY_DETAILS
    if hidden > 0:
        summary += f"; and {hidden} more problem{'s' if hidden > 1 else ''}"
    return summary


def contract_message(boundary: str, details: Sequence[str] = ()) -> str:
    """Name the rejected boundary and the first problems found in it."""
    summary = detail_summary(details)
    return f"invalid {boundary}: {summary}" if summary else f"invalid {boundary}"


def problem_summary(error: BaseException) -> str:
    """Describe a failure for a message that already names where it came from."""
    return detail_summary(getattr(error, "details", ())) or str(error)


class ContractViolation(InputError):
    """Validated external data does not match a named XUI Lab contract."""

    def __init__(self, boundary: str, details: Sequence[str] = ()):
        self.boundary = boundary
        self.details = tuple(details)
        super().__init__(contract_message(boundary, self.details))


class CapabilityError(XUILabError):
    """The selected runtime does not provide a required capability."""

    def __init__(self, message: str, *, capability: str | None = None) -> None:
        super().__init__(message)
        self.capability = capability


class RuntimeFailure(XUILabError):
    """The fork runtime failed or violated the JSON-lines protocol."""


class AssertionFailure(XUILabError):
    """A structural expectation failed."""

    def __init__(
        self,
        message: str,
        *,
        tree_excerpt: dict[str, Any] | None = None,
        selector: Any = None,
    ) -> None:
        super().__init__(message)
        self.tree_excerpt = tree_excerpt
        self.selector = selector
