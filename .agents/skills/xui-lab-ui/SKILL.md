---
name: xui-lab-ui
description: Test and improve viewer LLFloater, LLPanel, and LLXUI changes with XUI Lab. Use for production UI behavior, layout, interaction, regression scenarios, and viewer UI or UX review in this repository. Skip work limited to login, world rendering, or the browser inspector frontend.
---

# XUI Lab UI work

Drive a real registered floater through the JSON CLI. The headed inspector is
for a person. Read [`README.md`](../../../README.md) for setup,
`docs/CLI_CONTRACT.md` for JSON fields, and `AGENTS.local.md` for local paths.

Stdout is JSON. Stderr is diagnostics. After a JSON command is accepted, a
failure also writes an `ErrorRecord`. Branch on `code`. Use `--jq` for jq
expressions. Use `--fields` when you only need a few keys. Do not parse prose.

## Explore or change

**Explore** when the user asks what the lab can see, what a subject does, or
for a UI review without code changes. Preflight, start a session only when the
operation is available, drive it with one-shot commands, and report. If lab
support is missing, name it and stop unless the user asks you to add it.

**Change** when editing XUI, viewer code, the adapter, scenarios, or the
inspector. If the requested interaction needs lab support that does not exist
yet, add that support first, prove it, then do the original UI work.

## Start an instance

You need a viewer checkout and an `xui-lab` binary built from the same Git
tree. The binary embeds the viewer commit. Preflight accepts an exact commit or
a different commit with an identical tree, which covers message-only history
rewrites. Rebuild only when preflight reports `source_mismatch`. Keep host
build commands in `AGENTS.local.md`.

```sh
RUNTIME=/absolute/path/to/xui-lab
SOURCE=/absolute/path/to/alchemy

./xui-lab --viewer-source alchemy="$SOURCE" \
  subjects --json --runtime "$RUNTIME" --jq '.subjects[].name'

./xui-lab --viewer-source alchemy="$SOURCE" \
  preflight --json --subject SUBJECT --operation click \
  --runtime "$RUNTIME" --jq '.operations[] | select(.name=="click")'
```

Run preflight with the same `--runtime` you will start. Pass `--request-id`
before the subcommand, or the CLI generates one.

- Available: continue.
- `missing_capability`: in explore mode, stop with the missing name and
  `suggestedOperations`. In change mode, add the smallest reusable operation
  or capability, prove it, then resume.
- `source_mismatch`: the source trees differ. Rebuild the runtime.

Then start a hidden session and keep the id:

```sh
SESSION=$(./xui-lab --viewer-source alchemy="$SOURCE" \
  session start test_widgets --runtime "$RUNTIME" --jq .sessionId)
```

Subjects can declare a default fixture. Preflight reports it at `.fixture`, and
launch commands load it when `--fixture` is absent. Use `--fixture PATH` only
to override that default.

`session status` and `session close` take that id. Close is idempotent. Dead
PIDs are removed on status and close. `session close`, `reload`, and `run`
accept `--dry-run`. Do not pass `--dry-run` on pointer, keyboard, scroll, or
drag commands. Use `interactive` only when a person asked to look at the
window.

## Drive it over JSON

One-shot commands need `--session`. They print one JSON document.

```sh
./xui-lab tree --session "$SESSION" --jq '.data.tree.control_id, .data.treeArtifact.path'
./xui-lab tree --session "$SESSION" --fields tree.path,tree.control_id
./xui-lab get --session "$SESSION" --label OK --jq .data.locator
./xui-lab click --session "$SESSION" --control-id CONTROL
./xui-lab double-click --session "$SESSION" --model-id MODEL_UUID
./xui-lab right-click --session "$SESSION" --model-id MODEL_UUID
./xui-lab fill --session "$SESSION" --control-id EDITOR --value "hello"
./xui-lab press --session "$SESSION" --control-id EDITOR --key Enter
./xui-lab scroll --session "$SESSION" --control-id SPINNER --clicks -2
./xui-lab capture --session "$SESSION" --name after-click --jq .data.path
./xui-lab session close "$SESSION"
```

`tree` and `get` return an excerpt. The full tree is an artifact with `path`,
`size`, and `sha256`. `--include-tree` inlines it and warns on stderr. Prefer
`--fields` or `--jq` over dumping the whole tree. Captures return PNG paths,
never image bytes.

Use one selector flag: `--role`, `--label`, `--placeholder`, `--text`,
`--model-id`, `--control-id`, or `--path`. Pair `--name` with `--role`.
Prefer role and accessible name, then label, placeholder, visible text, and
model ID. Use a control ID only when no user-visible selector is unique. A
path records XUI provenance and is the last fallback. `get` returns the shared
versioned selector at `.data.locator.selector`. Python, the CLI, the inspector,
Recorded Python, and replay use that contract.

For a stream of commands without restarting the viewer:

```sh
jq -nc --arg s "$SESSION" '{schemaVersion:1,command:"tree",session:$s}' \
  | ./xui-lab session jsonl "$SESSION"
```

`--timeout` bounds startup, socket waits, and runtime requests. Use
`operations --json` for argument shapes and `schema` when you change contracts.

Query layout findings through `.data.layout` and gate on
`.data.layout.actionableCount`. Findings carry their source location,
rectangles, and ancestor chain. The lab ignores one-pixel parent-edge rounding,
scroll content clipped at the viewport edge, generated composite children, and
host root overlap.

Call `window.expect_no_layout_diagnostics()` in a Python scenario. Pass
`path_prefix="/…"` to limit the assertion to one production subtree, or pass
`--strict-layout-diagnostics` to `run` for the whole subject. Strict runs check
each captured frame and the final frame. Capture sidecars include the frame's
layout findings even when strict mode is off.

## Inspect screenshots without filling context

`capture` returns an absolute PNG path, not pixels the model can see. Pass the
path to Codex's `view_image` tool. Start with `detail: high`. Use
`detail: original` only when the resized image hides needed detail. Never print
or inline image bytes.

If `view_image` shows a solid black frame, load the same path once more before
recapturing. If it stays black, inspect the PNG dimensions and pixel range.
After the session closes, compare its size and SHA-256 in
`artifact-manifest.json`. An unchanged file that displays correctly on retry
points to the image viewer, not XUI Lab's capture.

For each edit:

1. Build and open a session. Reload after an XUI edit. Rebuild and start a new
   session after a C++ edit.
2. Perform the user's task. Query only the relevant `get`, `tree --fields`, or
   `tree --jq` data. Leave full artifacts on disk.
3. Capture only states that answer a visual question and the final state. Load
   one PNG at a time, note the specific defect, and edit again.
4. Repeat the task and inspect the final PNG. Add structural scenario
   assertions for stable behavior.

Screenshots show clipping, spacing, alignment, text, and hierarchy. The tree
and event results prove state and input behavior. Use a highlighted capture to
identify a control, then an ordinary capture to judge the final pixels.

## Drive the production UI

Find the `LLFloaterReg` registration, controller, XUI, callbacks, and model.
Send input through the CLI or through `Window` and `Locator`. Start with the
ranked selector from `get`. Use a model UUID for generated rows. Use control
IDs and paths only as the fallbacks described above.

Map the request before clicking:

- Inspector panel size is browser layout, not viewer behavior.
- `resize-viewport` changes the host window and LLUI root.
- `resize-subject` sets deterministic floater geometry.
- `scroll` is wheel input. `drag-by` is a raw pointer drag. `drag-to` is
  semantic drag-and-drop and drops only if the production handler accepts.
- `fill` replaces text. `press` sends a key.

In Python, call `window.wait_for_stable()` instead of sleeping. Assert the
visible result and use `expect_handled()` for routing bugs. Follow
`tests/scenarios/test_floater.py` and `tests/scenarios/input_gestures.py`. A
handled rejection is not an accepted drop.

`inventory_explorer` is a declared subject. XUI reloads from the selected
checkout. C++ changes need a rebuilt `xui-lab` and a new session.

## Work as a user

Exercise the user's task from its initial state to the visible result. Inspect
rectangles and visibility or enabled chains before moving controls. When text
clips, find the parent that clips it.

Cover the states the change affects, the default size, a supported narrow
size, a wider size, and the relevant UI scales. Copy spacing, control
choices, button order, and terms from neighboring production XUI.

## Add missing lab support

Add only what the production interaction needs. Reuse the viewer's
controllers, models, input routing, and system boundaries.

1. Expose the operation or capability on `Window` or `Locator`.
2. Drive one meaningful action through normal LLUI dispatch.
3. Assert the visible or recorded result structurally.
4. Inspect the frame, tree, trace, diagnostics, and `runtime.log`.
5. Resume the original UI task.

Stop at login, networking, world simulation, an irreversible external action,
or an unresolved product decision. Report that boundary.

`adapter.json` is evidence. Add a subject or capability only after a scenario
proves it. Fail with the capability name when the adapter cannot supply the
state.

Pixels, direct callbacks, fixed sleeps, coordinate selectors, and fake models
are not proof. Open the PNGs and read the JSON. A passing run writes `diagnostics.json`,
`event-trace.json`, captures, and sidecars. A failure also tries `frame.png`,
`ui-tree.json`, and `diagnostics-runtime.json`.
