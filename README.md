# `xui-lab`

> [!CAUTION]
> **Here be dragons.** `xui-lab` is extremely unfinished. Expect sudden changes.
> Unless you are working on it, avert your eyes.

`xui-lab` runs production Alchemy `LLFloater` subclasses and their C++
controllers without a full viewer session. It is not an XUI-only layout
previewer. The lab loads XUI through the production floater code, sends normal
LLUI events, and uses real viewer models. A reduced viewer runtime replaces
login, networking, world simulation, and other external services at explicit
boundaries.

## What exists

- A Python `Window` and `Locator` API that finds controls by XUI path or model
  UUID, waits for stable UI state, performs input, and checks structural results.
- Clicks, double-clicks, right-clicks, text entry, key presses, screenshots, UI
  tree inspection, event traces, and failure artifacts.
- A headed inspector for picking controls, viewing runtime details, reloading
  XUI, replaying Python scenarios, resizing subjects, and recording locator
  calls.
- Hidden Python scenario runs against the same production UI path.

> [!WARNING]
> Only the Alchemy adapter and its `test_widgets` subject are usable today.
> Scrolling and drag-and-drop are not wired up.

Builds are local concerns and deliberately undocumented here. If you have made
it this far, read [`SPEC.md`](SPEC.md), [`forks.json`](forks.json), and the
[`Alchemy adapter contract`](adapters/alchemy/README.md), then inspect your own
build environment.
