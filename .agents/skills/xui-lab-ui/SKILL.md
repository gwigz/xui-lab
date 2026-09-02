---
name: xui-lab-ui
description: Test and improve viewer LLFloater, LLPanel, and LLXUI changes with XUI Lab. Use for production UI behavior, layout, interaction, regression scenarios, and viewer UI or UX review in this repository. Skip work limited to login, world rendering, or the browser inspector frontend.
---

# XUI Lab UI work

XUI Lab is not a mockup tool. It opens the selected viewer fork's real
registered UI, sends normal LLUI input, and inspects the production view tree.
Keep that path intact.

Use the `xui-lab` CLI, Python scenarios, and their structured artifacts as the
agent control plane. Do not use browser automation to drive captured frames or
make it a prerequisite for verification. The browser inspector is optional for
a person to view until the CLI exposes equivalent one-shot and session commands.

## Choose a mode

Use **explore mode** when the user asks what the lab can see, what an existing
subject does, or for a UI review without code changes. Resolve the selected
source and runtime, open the subject, inspect declared operations, exercise the
task, and report observations. Report missing lab support without changing it
unless the user asks for implementation.

Use **change mode** when editing XUI, viewer code, the adapter, scenarios, or
the inspector. Implement any missing local lab support that the requested
production interaction needs, then follow the complete process below.

## Preflight the requested interaction

Before driving the UI, translate the user request into one concrete target and
one declared operation:

- Browser inspector panel size is browser layout, not viewer behavior.
- `resize_viewport()` changes the host window and LLUI root.
- `resize_subject()` sets deterministic floater geometry for a test state.
- `Locator.scroll()` and `Window.scroll_at()` route wheel clicks through
  `LLWindowCallbacks`.
- `Locator.drag_by()` and `Window.drag()` send raw pointer gestures. Use them
  for interactions such as floater resizing.
- `Locator.drag_to()` offers semantic cargo to a target through
  `LLView::handleDragAndDrop`. It drops only after the production handler
  accepts the cargo.
- `fill()` replaces text. `type_text()` inserts at the current selection.

Read `window.input_operations` or the inspector's reported operations before
acting. In explore mode, stop with the missing operation name. In change mode,
add the smallest reusable operation that exposes the production path, prove it,
and resume the requested work. Do not claim that a setup API proves event
routing.

## Add missing lab support in change mode

Touch the CLI, Python API, inspector, adapter, runtime, fixture, or scenario
only where the production interaction requires it. Preserve the selected
viewer's controllers, models, input routing, and system boundaries. Do not
replace missing production behavior with a mock.

Prove new support before relying on it:

1. Expose the operation or capability through the public `Window` or `Locator`
   API.
2. Drive one meaningful interaction through normal production input dispatch.
3. Assert the visible or recorded result structurally.
4. Inspect the frame, tree, trace, diagnostics, and runtime log.
5. Resume the original UI task with the new support.

Stop when the required support would expand the task into login, networking,
world simulation, an irreversible external action, or an unresolved product
decision. Report that boundary.

## Change process

1. Read `AGENTS.md`, `AGENTS.local.md` when present, `README.md`, `SPEC.md`,
   `TODO.md`, `forks.json`, and the selected adapter.
2. Inspect both worktrees. Run `./xui-lab check` and record any baseline
   failure.
3. Select one viewer source. Use it for checks, builds, interactive runs, and
   scenarios.
4. Find the `LLFloaterReg` registration, controller, XUI file, callbacks, and
   model behind the affected UI.
5. Open the declared subject through the CLI or a focused Python scenario.
   Exercise the user task through `Window` and `Locator` operations.
6. Query affected controls and read their IDs, paths, source locations,
   rectangles, state chains, focus, and mouse capture.
7. Fix the production XUI or controller. Reload XUI edits. Rebuild and restart
   after C++ edits.
8. Add or update a structural scenario. Run it in a fresh process and inspect
   every artifact.
9. Run the checks that match the files you changed. Inspect both worktrees
   again before handoff.

## Keep one viewer source

The binary embeds the viewer commit. The controller rejects a binary that does
not match the selected source. Do not check one checkout and build another.

Use the pinned submodule or pass the same override to every lab command:

```sh
./xui-lab \
  --viewer-source alchemy=/absolute/path/to/alchemy \
  interactive test_widgets \
  --runtime /absolute/path/to/xui-lab \
  --width 1024 \
  --height 700 \
  --ui-scale 1.0 \
  --artifacts /absolute/path/to/artifacts \
  --artifact-id floater-review
```

Replace `test_widgets` with a subject declared in the selected adapter. Keep
machine-specific build commands and paths in `AGENTS.local.md`.

Do not edit a detached viewer submodule. Use a viewer-owned branch or worktree.
Do not update the submodule pointer unless the user asks.

## Run production UI

1. Open a real registered `LLFloater` or `LLPanel` inside the lab's
   `LLFloaterView`.
2. Reuse production XUI, controllers, models, rendering, callbacks, and action
   rules.
3. Send input through `Window` and `Locator`. Let normal LLUI dispatch choose
   the handler.
4. Locate controls by `control_id` after inspecting the tree. Treat an absolute
   XUI path as provenance, not identity: generated siblings can share it. Use a
   stable model UUID for model-backed items when layout can move them.
5. Load deterministic fixtures into the real viewer model. Never copy filters,
   permissions, selection rules, or menu rules into the lab.
6. Stop login, network, world, URL, and file-dialog effects only at named system
   boundaries. Record the attempted effect for assertions.

A floater that opens is not proven. Its meaningful interactions have to work.
Code that mentions a subject does not make it supported. Trust `adapter.json`
and the current status in `README.md`.

## Work on the UI as a user

Name the task the floater helps a user finish. Exercise that task from its
initial state to the visible result.

- Inspect before moving controls. Read the local, screen, and clipping
  rectangles. Check the visibility and enabled chains.
- When text clips, find the parent that clips it. Making the whole floater
  taller by reflex usually hides the bug.
- Test the states the change affects. These may include empty, populated,
  selected, disabled, focused, menu-open, long-text, and failed-effect states.
- Test the intended default size, the supported narrow size, a wider size, and
  the UI scales relevant to the issue.
- Check clipping, overlap, reading order, action placement, focus, and whether
  the primary task stays obvious.
- Copy spacing, control choices, button order, and terms from neighboring
  production XUI. Browser UI fashion is not a viewer convention.
- If the codebase has no useful precedent, compare two or three small XUI
  variants at the same state and viewport. Keep the captures in ignored
  artifacts. Choose the one that makes the task clearest across sizes.

XUI edits load from the selected source checkout. Use **Reload** to destroy and
recreate the subject. C++ changes need a rebuild of the fork-specific
`xui-lab` executable and a new interactive process.

## Write scenarios that prove behavior

Follow `tests/scenarios/test_floater.py`. Define one `SCENARIO` value and one
`run(window)` function per module.

1. Name the fork, subject, viewport, capabilities, and optional fixture.
2. Call `window.wait_for_stable()` instead of sleeping.
3. Use only operations declared by `window.input_operations`. Use `scroll()`
   for wheel input, `drag_by()` for raw pointer drag, and `drag_to()` for
   semantic drag-and-drop.
4. Call `expect_handled()` when the bug involves event routing.
5. Assert the visible result. Use control state, rectangles, focus, menus,
   selection, values, drag acceptance, drop state, or recorded effects.
6. Capture the final state after the structural assertions pass.

Run one scenario with this shape:

```sh
./xui-lab \
  --viewer-source alchemy=/absolute/path/to/alchemy \
  run tests/scenarios/test_floater.py \
  --runtime /absolute/path/to/xui-lab \
  --artifacts /absolute/path/to/artifacts
```

With no scenario path, `xui-lab run` runs every module in `tests/scenarios/`.

For a resizable floater, prove both geometry setup and the user gesture:

```py
drag = window.get_by_control_id(handle_id).drag_by(dx=80, dy=-40).expect_handled()
assert drag.data["mouseCaptureAfterDown"]["control_id"] == handle_id
assert drag.data["mouseCaptureAfter"] is None
window.get_by_path(floater_path).expect_screen_rect(expected_rect)
```

Derive `expected_rect` from the declared starting geometry and handle
direction. Also assert that the drag acquired mouse capture after pointer down
and released it after pointer up when diagnosing routing.

For wheel or semantic drag-and-drop behavior, follow
`tests/scenarios/input_gestures.py`. Assert the value change caused by wheel
input. For drag-and-drop, assert `handled`, `acceptance`, `accepted`, and
`dropped`. A handled rejection proves production routing, but it does not prove
an accepted drop. Keep Inventory Explorer work undeclared until its production
subject and capabilities pass their own scenario.

## Reject weak tests

- **Screenshot-only proof.** Pixels do not prove input, focus, selection,
  clipping, or menu state.
- **Direct callback calls.** They skip LLUI dispatch and can hide the bug.
- **Fixed sleeps.** Wait for a stable production tree.
- **Screen-coordinate selectors.** Use control IDs or model UUIDs unless the
  coordinate itself is the behavior under test.
- **Fake viewer models.** Fixtures feed the production model. They do not
  replace it.
- **A stale binary.** Check the fork commit recorded by the binary and the
  artifacts.
- **Unproven capabilities.** Do not add a subject or capability to
  `adapter.json` because initialization succeeded.
- **Pretty failure captures.** The failure needs the tree, trace, diagnostics,
  and runtime log too.

## Add subjects and capabilities carefully

Preserve the production owner. Register the real controller through
`LLFloaterReg`, retain it through the selected viewer's build graph, and load
resources from the same viewer source. Do not add a copied production source
list.

Add one named capability for each real boundary the subject needs. Fail with
that capability name when the adapter cannot supply the state. Test malformed
or missing input at the process boundary.

Treat `adapter.json` as evidence, not a wish list. Before declaring support:

1. Build the runtime from the selected viewer source.
2. Open the production subject with its fixture.
3. Drive one meaningful action through normal LLUI input.
4. Assert the visible result and any recorded external effect.
5. Inspect the frame, tree, trace, diagnostics, and log.
6. Add only the subject and capabilities that the scenario proved.

## Inspect the proof

A passing scenario writes `diagnostics.json`, `event-trace.json`, captures, and
a JSON sidecar for each capture. A failure also attempts to write `frame.png`,
`ui-tree.json`, and `diagnostics-runtime.json`. The runtime log is
`runtime.log`.

Open every PNG. Read the JSON. Confirm the fork, commit, subject, fixture,
viewport, UI scale, overlay state, locator, input result, and assertion result.
A green exit code is not a substitute for reading the proof.

## Finish the right checks

Always run `./xui-lab check` against the pinned source. When you used an
override, run the check again with the same `--viewer-source` value.

For Python changes, run the pinned Ruff checks and unit suite from `AGENTS.md`.
For adapter C++, run `./xui-lab cpp format --check` and `clang-tidy` with the
selected build's `compile_commands.json`. Never pass viewer-submodule files to
the lab formatter or linter.

For viewer C++ or XUI changes, run the selected fork's build and checks. Rerun
the affected scenario against the same viewer source.

Report the selected fork, viewer commit, viewer source, commands, observed
behavior, artifact paths, and unfinished capability work. Do not push a branch,
commit, tag, artifact, or submodule pointer unless the user asks.
