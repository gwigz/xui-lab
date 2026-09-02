"""Exercise browser-equivalent text input through production LLUI."""

from xui_lab import Capability, Scenario, Viewport, Window
from xui_lab.errors import AssertionFailure

TEXT_EDITOR = "/Floater View/floater_test_widgets/test_text_editor"


def visible_labels(node: dict[str, object]) -> list[str]:
    labels: list[str] = []
    if node.get("visible_chain") is True and isinstance(node.get("label"), str):
        labels.append(str(node["label"]))
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                labels.extend(visible_labels(child))
    return labels


def run(window: Window) -> None:
    window.advance_frames(2)
    window.wait_for_stable()

    editor = window.get_by_path(TEXT_EDITOR)
    editor.fill("alpha beta").expect_handled()
    rect = editor.resolve().info["screen_rect"]
    if not isinstance(rect, dict):
        raise AssertionFailure("text editor does not expose a screen rectangle")
    center_x = (int(rect["left"]) + int(rect["right"])) // 2
    center_y = (int(rect["bottom"]) + int(rect["top"])) // 2
    window.double_click_at(center_x, center_y).expect_handled()
    editor.press("A", modifiers=("control",)).expect_handled()
    editor.type_text("Replaced").expect_handled()
    editor.expect_value("Replaced")

    editor.right_click().expect_handled()
    labels = visible_labels(window.query_tree())
    if "(unknown)" in labels:
        raise AssertionFailure("text editor menu exposes placeholder suggestions")
    if "Select All" not in labels:
        raise AssertionFailure("text editor context menu did not open")
    window.capture("text-input-menu", highlight=editor)


SCENARIO = Scenario(
    id="text_input",
    fork="alchemy",
    subject="test_widgets",
    viewport=Viewport(1024, 700, 1.0),
    capabilities=frozenset({Capability("input"), Capability("inspection")}),
    run=run,
)
