# Remaining work

This checklist tracks the work left to implement [SPEC.md](SPEC.md). Complete
the sections in order. Do not declare a capability in
[`adapter.json`](adapters/alchemy/adapter.json) until a real C++ runtime
scenario proves it.

The target developer experience resembles Playwright: launch one production
UI subject, locate controls, send normal input, inspect state, make structural
assertions, and retain useful evidence after failure. The API must keep LLUI
semantics where they matter. It must not introduce a parallel widget model.

The repository checks and 15 Python controller tests pass. The public adapter
currently declares only `input` and `inspection` for `test_widgets`. Existing
captures are stale because their metadata reports Alchemy commit `cd9c6bbd`.
Select and build one current Alchemy source before treating a runtime result as
evidence.

## Stabilize the process boundary

- [x] Contain every runtime capture path beneath the scenario artifact
  directory. Reject absolute paths, `..` components, and capture names that
  create subdirectories.
- [x] Add bounded request and shutdown waits. Report whether the runtime
  exited, stalled, closed its response stream, or returned an invalid response.
- [x] Add controller tests for each timeout and process-failure case.
- [x] Implement the runtime `diagnostics` operation. Include focus, mouse
  capture, the visible menu, the active subject, viewport state, and graphics
  information.
- [x] Force an assertion failure and verify that the runner writes `frame.png`,
  `ui-tree.json`, `event-trace.json`, `diagnostics.json`,
  `diagnostics-runtime.json`, and `runtime.log` before it exits nonzero.
- [x] Keep the runner as the parent process. Each scenario starts a fresh
  runtime so the runner can enforce timeouts and collect crash evidence.

## Reuse the viewer's event APIs

- [x] Inventory the `LLEventAPI` operations available to the reusable Alchemy
  UI target. Record which operations work without login, world state, or
  network services.
- [ ] Add one lab-specific `LLEventAPI` for lifecycle operations that the
  viewer does not provide: initialize, install capabilities, advance frames,
  wait for stability, resize, capture, reload, diagnostics, and shutdown.
- [ ] Keep the existing parent-controlled JSON-lines transport. Translate each
  validated request to LLSD and dispatch it through `LLEventPumps`.
- [ ] Expose event API and operation metadata to the controller. Do not expose
  an API unless the selected subject declares the capabilities it requires.
- [ ] Prove the bridge with one existing inspection operation, preferably
  `LLWindow.getSubtree`, before migrating other commands.
- [ ] Reuse or extract the path-addressed input and inspection behavior in
  `LLWindowListener`. Its current `LLViewerWindow` dependency must not force the
  lab to construct the normal viewer application.
- [ ] Reuse `LLFloaterReg`, `UI`, and subject-specific event APIs where they
  preserve the production behavior under test.
- [ ] Delete each duplicate lab implementation after its existing viewer API
  passes the same runtime scenario. Do not retain two command paths.
- [ ] Use LEAP protocol and introspection code as prior art. Do not make the lab
  controller a viewer-launched LEAP child process.

## Add a Playwright-style Python API

- [ ] Introduce `Lab`, `Window`, and `Locator` types over the typed runtime
  protocol. Keep raw command access available for adapter development.
- [ ] Make locators resolve immediately before every action and assertion. Do
  not retain runtime view pointers across layout, fixture, or reload changes.
- [ ] Add `get_by_path()` and `get_by_model_id()` first. Add label and role
  locators only after LLUI supplies an unambiguous production mapping.
- [ ] Fail a locator operation when it resolves to zero or multiple controls.
  Include matching paths, runtime classes, and source provenance in the error.
- [ ] Add locator actions for click, double-click, right-click, fill, key
  input, scroll, and drag-to as the runtime supports them.
- [ ] Add structural expectations for visibility, enabled state, value,
  selection, focus, rectangles, menus, handled events, and recorded effects.
- [ ] Add automatic stability waits around actions and expectations. Report the
  changing tree state when the wait times out.
- [ ] Let Python tests and JSON scenarios use the same typed operations,
  assertions, capability declarations, artifact naming, and failure evidence.

## Finish the headed workflow

- [ ] Implement `--interactive` with a visible SDL window and the same subject
  host, renderer, capabilities, and commands used in scenario mode.
- [ ] Add exact viewport resizing. Report both pixel size and LLUI size after
  every resize.
- [ ] Add pointer picking by screen position and return the frontmost visible
  control's locator, runtime class, source, and rectangles.
- [ ] Add keyboard and text input through the production LLUI event path.
- [ ] Report focus and mouse-capture changes after every input operation.
- [ ] Add source-XUI reload and scenario replay. Prove that interactive reload
  does not require a process restart.
- [ ] Build a companion inspector that does not alter subject layout. Show the
  selected control, path, class, source, rectangles, visibility chain, enabled
  chain, focus, mouse capture, and hit-test order.
- [ ] Add hover highlighting, `copy locator`, fixture selection, subject
  selection, screenshot capture, and UI-tree export.
- [ ] Record interactive actions as editable Python locator calls. Treat the
  recorder as a starting point for a test, not as the assertion oracle.
- [ ] Keep the inspector overlay out of ordinary captures. Record overlay state
  in capture metadata.

## Prove the design with Inventory Explorer

- [ ] Make model-ID targeting choose a visible `LLFolderViewItem` with a usable
  screen rectangle. Do not fall back to a hidden item for input.
- [ ] Fix the production right-click path for `Known Notecard`. The normal LLUI
  event route must select the item and leave the Inventory Explorer context menu
  visible.
- [ ] Return each visible production menu entry's label, path, enabled state,
  and source provenance through a concise menu locator result.
- [ ] Add an Inventory Explorer test that loads
  [`inventory-explorer.json`](fixtures/inventory-explorer.json), opens `Lab
  Fixtures`, and right-clicks `Known Notecard` by model UUID.
- [ ] Assert that the input was handled, the popup is visible, and known
  production entries include both an enabled action and a disabled action.
- [ ] Capture the open context menu and inspect the PNG and structural trace.
- [ ] Add `inventory_explorer` and its proven `inventory_model`,
  `agent_identity`, and `menus` capabilities to
  [`adapter.json`](adapters/alchemy/adapter.json) only after the test passes.
- [ ] Add the empty-inspector regression at several widths. Assert that its
  text remains inside the effective clipping rectangle, then inspect each
  capture.

## Add capability packs at real boundaries

- [ ] Represent each subject requirement as a named capability with typed
  fixture input and an explicit unavailable error.
- [ ] Add a convenience capability pack only as a composition of named
  capabilities. Keep its expanded configuration inspectable in artifacts.
- [ ] Add avatar-state and cached-name fixtures when a registered subject first
  requires them.
- [ ] Intercept URL launches, file dialogs, and network requests at their
  system boundaries. Record each attempted effect and its declared result.
- [ ] Add one real scenario for every new boundary before declaring its
  capability.
- [ ] Prove that scenario mode does not contact the network. Fail with the
  missing capability name when a subject requests an undeclared service.
- [ ] Add drag-and-drop through the production handler when the first scenario
  needs it. Do not copy acceptance or permission rules.

## Complete inspection and failure diagnostics

- [ ] Verify that every tree node reports runtime class, XUI path, source file
  and line, local rectangle, screen rectangle, clipping rectangle, visibility
  chain, enabled chain, focus state, mouse-capture state, and hit-test order.
- [ ] Add overlap and text-clipping diagnostics based on production layout
  state.
- [ ] Record the scenario step, graphics environment, fixture, UI scale, fork,
  commit, and overlay state in every capture sidecar.
- [ ] Make locator and expectation failures include the smallest relevant tree
  excerpt instead of requiring the user to search the complete UI tree.

## Expand behavior coverage

- [ ] Prove shared selection across Inventory Explorer's tree, single-folder
  list, and grid views.
- [ ] Add tests for folder navigation, search, inspector details, and the
  holding tray.
- [ ] Add a drag-and-drop test through the production handler.
- [ ] Keep structural assertions as the pass condition. Add platform-specific
  image comparisons only after the behaviors pass.

## Harden contracts and isolation

- [ ] Define and validate every runtime operation at the Python input boundary.
  Keep commands typed after parsing.
- [ ] Validate all fixture fields and reject unknown keys before starting the
  C++ process.
- [ ] Add runtime contract tests for metadata, source mismatch, API metadata,
  capability reporting, missing fixtures, unavailable capabilities, clean
  shutdown, visible and hidden rendering, input, menu routing, and capture.
- [ ] Verify that a fresh process starts for every scenario and that a failed
  scenario cannot affect the next one.
- [ ] Test that interactive mode and scenario mode dispatch identical typed
  operations through the same subject host.

## Rebuild and hand off

- [ ] Select one Alchemy source and use it for checks, build, launch, and every
  scenario. Do not reuse the stale `cd9c6bbd` binary or artifacts.
- [ ] Build through the selected checkout's supported local workflow. Pass the
  resulting executable to `xui-lab run --runtime`.
- [ ] Run the repository checks and controller tests:

  ```sh
  python3 tools/check.py
  python3 tools/check.py \
    --viewer-source alchemy=/absolute/path/to/alchemy
  python3 -m unittest discover -s tests -v
  ```

- [ ] Run every scenario against the fresh binary. Inspect every PNG, JSON
  sidecar, event trace, diagnostic file, and runtime log.
- [ ] Update [`README.md`](README.md),
  [`scenarios/README.md`](scenarios/README.md), and
  [`fixtures/README.md`](fixtures/README.md) to describe the implemented API,
  commands, file formats, and interactive workflow. Remove specification-stage
  claims.
- [ ] Inspect the superproject, selected Alchemy checkout, and pinned submodule
  status. Report the selected fork, exact commit, commands, observed behavior,
  artifact paths, and remaining placeholders.
- [ ] Decide the repository and viewer-code licensing terms before distributing
  binaries or accepting contributions from other forks.
