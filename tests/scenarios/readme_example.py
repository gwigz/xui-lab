"""Build the README example with production LLUI input."""

from xui_lab import Capability, Scenario, Viewport, Window
from xui_lab.errors import AssertionFailure

CHECKBOX = "/Floater View/floater_test_widgets/test_checkbox"
CHECKBOX_BUTTON = f"{CHECKBOX}/CheckboxCtrl Button"
LINE_EDITOR = "/Floater View/floater_test_widgets/test_line_editor"
SPINNER = "/Floater View/floater_test_widgets/test_spinner"
TEXT_EDITOR = "/Floater View/floater_test_widgets/test_text_editor"


def run(window: Window) -> None:
    window.advance_frames(2)
    window.wait_for_stable()
    window.resize_viewport(1024, 700, ui_scale=1.0)
    window.reload()

    line_editor = window.get_by_path(LINE_EDITOR)
    line_editor.fill("XUI Lab was here.").expect_handled()
    line_editor.expect_value("XUI Lab was here.")

    checkbox = window.get_by_path(CHECKBOX)
    checkbox.expect_value(False)
    window.get_by_path(CHECKBOX_BUTTON).click().expect_handled()
    checkbox.expect_value(True)

    spinner = window.get_by_path(SPINNER)
    before = spinner.resolve().info.get("value")
    spinner.scroll(-2).expect_handled()
    after = spinner.resolve().info.get("value")
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        raise AssertionFailure("spinner values must be numeric")
    if after <= before:
        raise AssertionFailure(
            f"upward wheel input did not increase the spinner: {before} -> {after}"
        )

    editor = window.get_by_path(TEXT_EDITOR)
    message = "The editor got this text.\nThe tree reports it too."
    editor.fill(message).expect_handled()
    editor.expect_value(message)
    window.capture("readme-example", highlight=editor)


SCENARIO = Scenario(
    id="readme_example",
    fork="alchemy",
    subject="test_widgets",
    viewport=Viewport(1024, 700, 1.0),
    capabilities=frozenset({Capability("input"), Capability("inspection")}),
    run=run,
)
