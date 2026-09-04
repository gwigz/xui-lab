"""Run the Inventory Explorer responsive checks at 1.25 UI scale."""

from dataclasses import replace

from tests.scenarios.inventory_responsive_layout import SCENARIO as BASE_SCENARIO
from xui_lab import Viewport

SCENARIO = replace(
    BASE_SCENARIO,
    id="inventory_responsive_layout_scaled",
    viewport=Viewport(1280, 875, 1.25),
)
