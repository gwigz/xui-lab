"""Exercise the production test floater through Window and Locator."""

from xui_lab import Capability, Scenario, Viewport, Window

CHECKBOX = "/Floater View/floater_test_widgets/test_checkbox"
CHECKBOX_BUTTON = f"{CHECKBOX}/CheckboxCtrl Button"


def run(window: Window) -> None:
    window.advance_frames(2)
    window.wait_for_stable()
    window.resize_viewport(1024, 700, ui_scale=1.0)
    window.reload()

    checkbox = window.get_by_path(CHECKBOX)
    checkbox.expect_value(False)
    window.get_by_path(CHECKBOX_BUTTON).click().expect_handled()
    checkbox.expect_value(True)
    window.capture("test-floater", highlight=checkbox)


SCENARIO = Scenario(
    id="test_floater",
    fork="alchemy",
    subject="test_widgets",
    viewport=Viewport(1024, 700, 1.0),
    capabilities=frozenset({Capability("input"), Capability("inspection")}),
    run=run,
)
