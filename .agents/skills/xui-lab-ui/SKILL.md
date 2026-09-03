---
name: xui-lab-ui
description: Test and improve viewer LLFloater, LLPanel, and LLXUI changes with XUI Lab. Use for production UI behavior, layout, interaction, regression scenarios, and viewer UI or UX review in this repository. Skip work limited to login, world rendering, or the browser inspector frontend.
---

# XUI Lab UI work

Open a real registered floater, send normal LLUI input, and inspect the
production tree. Do that with the JSON CLI. The headed inspector is for a
person. Humans start from [`README.md`](../../../README.md). Repo checks live
in `AGENTS.md`. JSON fields and exit statuses live in `docs/CLI_CONTRACT.md`.
Machine-specific build paths live in `AGENTS.local.md` when that file exists.

Stdout is JSON. Stderr is diagnostics. After a JSON command is accepted, a
failure also writes an `ErrorRecord`. Branch on `code`. Pipe stdout to `jq`.
Use `--fields` when you only need a few keys. Do not parse prose.

## Explore or change

**Explore** when the user asks what the lab can see, what a subject does, or
for a UI review without code changes. Preflight, start a session only when the
operation is available, drive it with one-shot commands, and report. If lab
support is missing, name it and stop unless the user asks you to add it.

**Change** when editing XUI, viewer code, the adapter, scenarios, or the
inspector. If the requested interaction needs lab support that does not exist
yet, add that support first, prove it, then do the original UI work.

## Start an instance

You need a viewer checkout and a matching `xui-lab` binary. The binary embeds
the viewer commit. Rebuild until `--metadata` matches `git rev-parse HEAD`.
Keep host build commands in `AGENTS.local.md`.

```sh
RUNTIME=/absolute/path/to/xui-lab
SOURCE=/absolute/path/to/alchemy

./xui-lab --viewer-source alchemy="$SOURCE" \
  subjects --json --runtime "$RUNTIME" | jq -r '.subjects[].name'

./xui-lab --viewer-source alchemy="$SOURCE" \
  preflight --json --subject SUBJECT --operation click \
  --runtime "$RUNTIME" | jq '.operations[] | select(.name=="click")'
```

Run preflight with the same `--runtime` you will start. Pass `--request-id`
before the subcommand, or the CLI generates one.

- Available: continue.
- `missing_capability`: in explore mode, stop with the missing name and
  `suggestedOperations`. In change mode, add the smallest reusable operation
  or capability, prove it, then resume.
- `source_mismatch`: rebuild until `--metadata` matches.

Then start a hidden session and keep the id:

```sh
SESSION=$(./xui-lab --viewer-source alchemy="$SOURCE" \
  session start test_widgets --runtime "$RUNTIME" | jq -r .sessionId)
```

`session status` and `session close` take that id. Close is idempotent. Dead
PIDs are removed on status and close. Use `interactive` only when a person
asked to look at the window.

## Drive it over JSON

One-shot commands need `--session`. They print one JSON document.

```sh
./xui-lab tree --session "$SESSION" | jq '.data.tree.control_id, .data.treeArtifact.path'
./xui-lab tree --session "$SESSION" --fields tree.path,tree.control_id
./xui-lab get --session "$SESSION" --label OK | jq .data.locator
./xui-lab click --session "$SESSION" --control-id CONTROL
./xui-lab fill --session "$SESSION" --control-id EDITOR --value "hello"
./xui-lab press --session "$SESSION" --control-id EDITOR --key Enter
./xui-lab scroll --session "$SESSION" --control-id SPINNER --clicks -2
./xui-lab capture --session "$SESSION" --name after-click | jq .data.path
./xui-lab session close "$SESSION"
```

`tree` and `get` return an excerpt. The full tree is an artifact with `path`,
`size`, and `sha256`. `--include-tree` inlines it and warns on stderr. Prefer
`--fields` or `jq` over dumping the whole tree. Captures return PNG paths,
never image bytes.

Selectors, one flag only: `--control-id`, `--model-id`, `--path`, `--role`,
`--label`, `--placeholder`, `--text`. `--name` goes with `--role`. `--path` is
provenance. Prefer a visible name or a model id. Conflicting flags fail at
parse time.

For a stream of commands without restarting the viewer:

```sh
jq -nc --arg s "$SESSION" '{schemaVersion:1,command:"tree",session:$s}' \
  | ./xui-lab session jsonl "$SESSION"
```

`--timeout` bounds startup, socket waits, and runtime requests. Use
`operations --json` for argument shapes and `schema` when you change contracts.

## Drive the production UI

Find the `LLFloaterReg` registration, controller, XUI, callbacks, and model.
Send input through the CLI or through `Window` and `Locator` so LLUI picks the
handler. Locate by `control_id` after reading `tree` or `get`. Treat an XUI
path as provenance, not identity. Use a model UUID when layout can move the
row.

Map the request before clicking:

- Inspector panel size is browser layout, not viewer behavior.
- `resize-viewport` changes the host window and LLUI root.
- `resize-subject` sets deterministic floater geometry.
- `scroll` is wheel input. `drag-by` is a raw pointer drag. `drag-to` is
  semantic drag-and-drop and drops only if the production handler accepts.
- `fill` replaces text. `press` sends a key.

When you write Python, call `window.wait_for_stable()` instead of sleeping.
Assert the visible result. `expect_handled()` when the bug is routing. A setup
API does not prove event routing. Follow `tests/scenarios/test_floater.py`.
For wheel or drag-and-drop, follow `tests/scenarios/input_gestures.py`. A
handled rejection is not an accepted drop.

Keep Inventory Explorer undeclared until its own scenario proves the subject
and capabilities. XUI reloads from the selected checkout. C++ changes need a
rebuilt `xui-lab` and a new session.

## Work as a user

Name the task the floater helps a user finish. Exercise that task from its
initial state to the visible result. Read local, screen, and clipping
rectangles plus visibility and enabled chains before moving controls. When
text clips, find the parent that clips it.

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

Pixels, direct callback calls, fixed sleeps, screen-coordinate selectors, and
fake viewer models are not proof. A green exit code is not proof either. Open
the PNGs and read the JSON. A passing run writes `diagnostics.json`,
`event-trace.json`, captures, and sidecars. A failure also tries `frame.png`,
`ui-tree.json`, and `diagnostics-runtime.json`.
