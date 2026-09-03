"""Right-click a known notecard in the production Inventory Explorer."""

from pathlib import Path

from xui_lab import Capability, Scenario, Viewport, Window
from xui_lab.errors import AssertionFailure

LAB_FIXTURES = "20000000-0000-4000-8000-000000000002"
KNOWN_NOTECARD = "30000000-0000-4000-8000-000000000001"

# Production entries that the notecard bridge supplies for a full-permission
# item the agent owns. Paste stays disabled because the lab starts with an
# empty clipboard.
MENU_FILE = "menu_al_inventory_explorer.xml"
ENABLED_ENTRY = "Copy"
DISABLED_ENTRY = "Paste"


def run(window: Window) -> None:
    window.wait_for_stable()

    folder = window.get_by_model_id(LAB_FIXTURES)
    folder.expect_visible()
    folder.double_click().expect_handled()
    folder.expect("open", True)

    notecard = window.get_by_model_id(KNOWN_NOTECARD)
    notecard.expect_visible()
    notecard.right_click().expect_handled()

    window.expect_menu_visible(True)
    notecard.expect_selected(True)

    known = (
        window.expect_menu_entry("Open"),
        window.expect_menu_entry(ENABLED_ENTRY, enabled=True),
        window.expect_menu_entry(DISABLED_ENTRY, enabled=False),
    )
    for entry in known:
        if not entry.source_file.endswith(MENU_FILE):
            raise AssertionFailure(
                f"menu entry {entry.label!r} came from {entry.source_file}, "
                f"expected {MENU_FILE}"
            )

    window.capture("known-notecard-context-menu", highlight=notecard)


SCENARIO = Scenario(
    id="inventory_explorer",
    fork="alchemy",
    subject="inventory_explorer",
    viewport=Viewport(1024, 700, 1.0),
    capabilities=frozenset(
        {
            Capability("input"),
            Capability("inspection"),
            Capability("inventory_model"),
            Capability("agent_identity"),
            Capability("menus"),
        }
    ),
    fixture=Path("fixtures/inventory-explorer.json"),
    run=run,
)
