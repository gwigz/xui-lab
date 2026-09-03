# Python scenarios

Each module defines one `SCENARIO`. Its `run(window)` function uses the public
`Window` and `Locator` API. `xui-lab run` opens a fresh runtime process for each
module. The headed inspector can replay the same function in the current
runtime process.

`input_gestures.py` proves that wheel input changes a production spinner. It
also proves that semantic drag-and-drop reaches a production text editor and
reports the editor's rejection of non-inventory cargo. Accepted inventory
drag-and-drop remains part of the Inventory Explorer work.

A module whose name starts with `_` stays out of scenario discovery and out of
a bare `xui-lab run`. Pass the file to run it anyway.
