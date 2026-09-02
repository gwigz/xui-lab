# Python scenarios

Each module defines one `SCENARIO`. Its `run(window)` function uses the public
`Window` and `Locator` API. `xui-lab run` opens a fresh runtime process for each
module. The headed inspector can replay the same function in the current
runtime process.
