# Python scenarios

Each module defines one `SCENARIO`. Its `run(window)` function uses the public
`Window` and `Locator` API. `xui-lab run` opens a fresh runtime process for each
module. The headed inspector can replay the same function in the current
runtime process.

`input_gestures.py` proves that wheel input changes a production spinner. It
also proves that semantic drag-and-drop reaches a production text editor and
reports the editor's rejection of non-inventory cargo.

`inventory_explorer_workflow.py` proves shared selection, folder navigation,
search, inspector details, and an accepted drop into the holding tray. The
scenario compares its capture with
`tests/baselines/<platform>/inventory-explorer-workflow.png` when that baseline
exists. To accept an intentional visual change on the current platform, run:

```sh
./scripts/update-image-baseline \
  artifacts/<run>/inventory_explorer_workflow/inventory-explorer-workflow.png \
  inventory-explorer-workflow.png
```

`inventory_visual_fixture.py` traverses the generated visual dataset. It proves
favorite and worn presentation, valid long-name handling, deterministic and
fallback thumbnails, nested navigation, and the top and bottom scroll
boundaries. Regenerate the fixture with `./scripts/generate-inventory-fixture`.
The schema audit fails if the checked-in copy drifts from the generator.

A module whose name starts with `_` stays out of scenario discovery and out of
a bare `xui-lab run`. Pass the file to run it anyway.
