"""Exercise wheel and semantic drag-and-drop production dispatch."""

from xui_lab import Capability, Scenario, Viewport, Window
from xui_lab.errors import AssertionFailure

CHECKBOX = "/Floater View/floater_test_widgets/test_checkbox"
SPINNER = "/Floater View/floater_test_widgets/test_spinner"
TEXT_EDITOR = "/Floater View/floater_test_widgets/test_text_editor"


def run(window: Window) -> None:
    window.advance_frames(2)
    window.wait_for_stable()

    spinner = window.get_by_path(SPINNER)
    before = spinner.resolve().info.get("value")
    spinner.scroll(-1).expect_handled()
    after = spinner.resolve().info.get("value")
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        raise AssertionFailure("spinner values must be numeric")
    if after <= before:
        raise AssertionFailure(
            f"upward wheel input did not increase the spinner: {before} -> {after}"
        )

    drop = (
        window.get_by_path(CHECKBOX)
        .drag_to(window.get_by_path(TEXT_EDITOR))
        .expect_handled()
        .data
    )
    if drop.get("acceptance") != "no":
        raise AssertionFailure("text editor unexpectedly accepted non-inventory cargo")
    if drop.get("accepted") is not False or drop.get("dropped") is not False:
        raise AssertionFailure("rejected drag-and-drop was reported as dropped")

    window.capture("input-gestures", highlight=spinner)


SCENARIO = Scenario(
    id="input_gestures",
    fork="alchemy",
    subject="test_widgets",
    viewport=Viewport(1024, 700, 1.0),
    capabilities=frozenset({Capability("input"), Capability("inspection")}),
    run=run,
)
