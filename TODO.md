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

Named capabilities, typed fixtures, and `missing_capability` errors already
exist. Scenarios list the expanded set. Do not add a convenience pack type
until a second subject needs the same bundle. Cached avatar names already
ship with `inventory_explorer`. Add avatar-state fixtures when a subject first
needs worn or Current Outfit folder state.

Interactive mode and scenario mode already share `Window`. `xui-lab run`
starts a fresh process per scenario. Structural assertions are the pass
condition.

## Intercept external effects

- [ ] Intercept URL launches, file dialogs, and network requests at their
  system boundaries. Record each attempted effect and its declared result.
- [ ] Add one real scenario that proves a recorded effect, then declare
  `external_effects`.
- [ ] Prove scenario mode does not contact the network. Fail with the missing
  capability name when a subject requests an undeclared service.

## Inspection diagnostics

Tree nodes already report class, path, source, rectangles, visibility and
enabled chains, focus, mouse capture, and hit-test order. `get` and `tree`
already return excerpts. Capture sidecars already record fork, commit,
fixture, UI scale, viewport, and overlay. The artifact manifest already lists
files.

- [ ] Add overlap and text-clipping diagnostics from production layout state.
- [ ] Put the scenario step and graphics environment on every capture sidecar.
- [ ] Link each automatic screenshot in the capture manifest to the action,
  selector, and sequence that produced it.
- [ ] On locator and expectation failures, include the smallest relevant tree
  excerpt in the error.
- [ ] In the headed inspector, add a scrubbable capture filmstrip. Scrubbing a
  historical frame shows that step's tree, selection, focus, recording, and
  diagnostics without mutating the live viewer.

## Inventory Explorer coverage

- [ ] Prove shared selection across tree, single-folder list, and grid views.
- [ ] Add tests for folder navigation, search, inspector details, and the
  holding tray.
- [ ] Add an accepted Inventory Explorer drag-and-drop case. Rejection of
  non-inventory cargo is already covered by `input_gestures.py`.
- [ ] Add platform-specific image comparisons only after those behaviors pass.

## Contract gaps

Metadata, source mismatch, missing fixtures, capability reporting, clean
shutdown, and a fresh process per scenario already have tests.

- [ ] Add runtime contract tests for visible versus hidden rendering and for
  capture sidecar schema.
