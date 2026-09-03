"""Click the production wiki URL in the test floater and record the launch."""

from xui_lab import Capability, Scenario, Viewport, Window
from xui_lab.errors import AssertionFailure

URL_TEXT = "/Floater View/floater_test_widgets/test_url_text"
WIKI_URL = "http://wiki.secondlife.com/wiki/XUI_Reference"


def run(window: Window) -> None:
    window.wait_for_stable()

    link = window.get_by_path(URL_TEXT)
    link.expect_visible()
    link.click().expect_handled()

    effect = window.expect_recorded_effect("url", WIKI_URL)
    if effect.get("kind") != "url" or effect.get("channel") != "open":
        raise AssertionFailure(
            f"wiki HTTP URL should record kind=url channel=open, got {effect!r}"
        )
    window.expect_no_recorded_effect("kind", "network")
    if window.diagnostics().get("httpService") is not False:
        raise AssertionFailure("scenario runtime started an HTTP service")
    window.capture("url-launch", highlight=link)


SCENARIO = Scenario(
    id="url_launch",
    fork="alchemy",
    subject="test_widgets",
    viewport=Viewport(1024, 700, 1.0),
    capabilities=frozenset(
        {Capability("input"), Capability("inspection"), Capability("external_effects")}
    ),
    run=run,
)
