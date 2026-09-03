# `xui-lab`

> [!CAUTION]
> This project is unfinished and changes often.

The lab runs production Alchemy `LLFloater` subclasses and their C++
controllers without a full viewer session. It loads XUI through production
floater code, sends normal LLUI events, and uses real viewer models. A reduced
runtime replaces login, networking, world simulation, and other external
services at explicit boundaries.

![The inspector showing the production test floater in T3 Code](.github/assets/xui-lab-in-t3-code.png)

## What exists

- A Python API for exact control targeting, wheel scrolling, raw pointer drag,
  semantic drag-and-drop, structural assertions, UI inspection, and failure
  artifacts.
- A headed inspector that captures the initial frame and refreshes it after UI
  actions. Interact mode routes clicks, wheel input, pointer drag, model-backed
  drag-and-drop, and key presses through LLUI. Inspect mode outlines hovered
  controls from the current production UI tree.
- Hidden scenario runs through the same production UI path.

## Run an input scenario

[`readme_example.py`](tests/scenarios/readme_example.py) uses `fill()` on the
line editor and multiline editor. It clicks the checkbox and sends two upward
wheel steps to the spinner, changing its value from `0.000` to `0.200`. After
each input, the scenario reads the control's value from the production view
tree. It writes the capture only after every check passes.

Run the example against an Alchemy checkout and its matching lab binary:

```sh
./xui-lab \
  --viewer-source alchemy=/path/to/alchemy \
  run tests/scenarios/readme_example.py \
  --runtime /path/to/xui-lab \
  --artifacts artifacts/readme-example
```

The runner reports the scenario and the proof directory:

```text
readme_example: passed [artifacts/readme-example/readme_example]
```

## Inspector frontend

The browser inspector is a React and TypeScript application in `inspector/`.
Vite builds it into the embedded `xui_lab/_inspector/` assets served by the
Python controller. Its Button, Input, Select, Tabs, and Toolbar components come
from the Coss UI registry. They use Base UI behavior and Coss neutral tokens.
Tailwind CSS supplies the generated utility styles.

Install the pinned frontend dependencies and run its complete check with:

```sh
npm ci --prefix inspector
npm run check --prefix inspector
```

For frontend work with hot reload, start an inspector backend on port 8765 and
then run `npm run dev --prefix inspector`. A viewer-free backend is available
for layout work:

```sh
python3 tests/integration/preview_inspector.py --capture /path/to/capture.png
npm run dev --prefix inspector
```

The production build records a source fingerprint. `./xui-lab check` fails
with the rebuild command when the embedded client is missing or stale.

## Check Python changes

Install the pinned tools from `requirements-dev.txt`. Then run the Python
checks and schema validation:

```sh
ruff check .
ruff format --check .
mypy
coverage run -m pytest
coverage report
./scripts/check-schemas
```

Pytest discovers tests under `tests/` but skips `tests/scenarios/`. Coverage
measures branches in `xui_lab` and enforces the current 59% floor.

> [!WARNING]
> Only the Alchemy adapter and its `test_widgets` subject are usable today.
> Inventory Explorer remains work in progress and is not declared as a usable
> subject.

`Locator.scroll()` and `Window.scroll_at()` route wheel input through the
production `LLWindowCallbacks` path. `Locator.drag_to()` offers cargo through
`LLView::handleDragAndDrop` and drops it only when the production handler
accepts it. Use `Locator.drag_by()` or `Window.drag()` for raw pointer gestures
such as floater resizing.

## Build performance

Debug arm64 timings from an Apple M2 Ultra on 2 September 2026:

| Workload | Ninja actions | Wall time |
| --- | ---: | ---: |
| Initial `xui-lab` target | 1,285 | 181.99 s |
| Full `alchemy-bin` target | 788 | 287.52 s |
| Lab commit-metadata rebuild | 7 | 14.00 s |
| One adapter source compile and relink | 2 | 6.94 s |
| No-op lab build and source sync | 0 | 5.65 s |

Dependencies were already installed, and the viewer reused dependency targets
built for the lab. A persistent build tree reduces an adapter edit to one
compile and one link.

For design and build details, read [`SPEC.md`](SPEC.md),
[`forks.json`](forks.json), and the
[`Alchemy adapter contract`](adapters/alchemy/README.md).
