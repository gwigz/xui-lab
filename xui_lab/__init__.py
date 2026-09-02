"""Controller for fork-specific xui-lab runtimes."""

from .api import ActionResult, Control, Lab, Locator, Window
from .domain import Capability, Comparison, Viewport
from .operations import (
    Capture,
    Diagnostics,
    Frames,
    ModelIdSelector,
    MouseButton,
    PathSelector,
    PointerAction,
    PointerEvent,
    QueryInventory,
    QueryMenus,
    QueryTree,
    QueryValue,
    Reload,
    Resize,
    WaitForStable,
)

__all__ = [
    "ActionResult",
    "Capability",
    "Capture",
    "Comparison",
    "Control",
    "Diagnostics",
    "Frames",
    "Lab",
    "Locator",
    "ModelIdSelector",
    "MouseButton",
    "PathSelector",
    "PointerAction",
    "PointerEvent",
    "QueryInventory",
    "QueryMenus",
    "QueryTree",
    "QueryValue",
    "Reload",
    "Resize",
    "Viewport",
    "WaitForStable",
    "Window",
    "__version__",
]

__version__ = "0.1.0"
