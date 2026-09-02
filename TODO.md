# Remaining work

This checklist tracks the work left to implement [SPEC.md](SPEC.md). Complete
the sections in order. Do not declare a capability in
[`adapter.json`](adapters/alchemy/adapter.json) until a real C++ runtime
scenario proves it.

The target API launches one production UI subject, locates controls, sends
normal LLUI input, inspects state, and makes structural assertions. After a
failure, it keeps the frame, UI tree, event trace, diagnostics, and runtime log.
The API must preserve LLUI semantics. It must not introduce a parallel widget
model.

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
- [ ] Build convenience capability sets by composing named capabilities. Record
  the expanded configuration in artifacts.
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
  Keep commands typed after validation.
- [ ] Validate all fixture fields and reject unknown keys before starting the
  C++ process.
- [ ] Add runtime contract tests for metadata, source mismatch, API metadata,
  capability reporting, missing fixtures, unavailable capabilities, clean
  shutdown, visible and hidden rendering, input, menu routing, and capture.
- [ ] Verify that a fresh process starts for every scenario and that a failed
  scenario cannot affect the next one.
- [ ] Test that interactive mode and scenario mode dispatch identical typed
  operations through the same subject host.

## Rebuild and verify

- [ ] Select one Alchemy source and use it for checks, build, launch, and every
  scenario. Do not reuse the stale `cd9c6bbd` binary or artifacts.
- [ ] Build through the selected checkout's supported local workflow. Pass the
  resulting executable to `xui-lab run --runtime`.
- [ ] Run the repository checks and controller tests:

  ```sh
  ./xui-lab check
  ./xui-lab \
    --viewer-source alchemy=/absolute/path/to/alchemy \
    check
  python3 -m unittest discover -s tests -v
  ```

- [ ] Run every scenario against the fresh binary. Inspect every PNG, JSON
  sidecar, event trace, diagnostic file, and runtime log.
- [ ] Update [`README.md`](README.md),
  [`tests/scenarios/README.md`](tests/scenarios/README.md), and
  [`fixtures/README.md`](fixtures/README.md) to describe the implemented API,
  commands, file formats, and interactive workflow. Remove specification-stage
  claims.
- [ ] Inspect the superproject, selected Alchemy checkout, and pinned submodule
  status. Report the selected fork, exact commit, commands, observed behavior,
  artifact paths, and remaining placeholders.
- [ ] Decide the repository and viewer-code licensing terms before distributing
  binaries or accepting contributions from other forks.
