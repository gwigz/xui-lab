"""Errors that may safely cross the command-line boundary."""


class XUILabError(Exception):
    """A user-facing xui-lab failure."""


class InputError(XUILabError):
    """A manifest, fixture, Python scenario, or command is invalid."""


class ContractViolation(InputError):
    """Validated external data does not match a named XUI Lab contract."""

    def __init__(self, boundary: str):
        self.boundary = boundary
        super().__init__(f"{boundary} violates the XUI Lab contract")


class CapabilityError(XUILabError):
    """The selected runtime does not provide a required capability."""

    def __init__(self, message: str, *, capability: str | None = None) -> None:
        super().__init__(message)
        self.capability = capability


class RuntimeFailure(XUILabError):
    """The fork runtime failed or violated the JSON-lines protocol."""


class AssertionFailure(XUILabError):
    """A structural expectation failed."""
