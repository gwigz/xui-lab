"""Errors that may safely cross the command-line boundary."""


class XUILabError(Exception):
    """A user-facing xui-lab failure."""


class InputError(XUILabError):
    """A manifest, fixture, scenario, or command is invalid."""


class CapabilityError(XUILabError):
    """The selected runtime does not provide a required capability."""


class RuntimeFailure(XUILabError):
    """The fork runtime failed or violated the JSON-lines protocol."""


class AssertionFailure(XUILabError):
    """A structural scenario assertion failed."""
