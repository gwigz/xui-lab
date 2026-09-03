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

## CLI control plane

- [ ] Add `xui-lab record --output FILE` and `xui-lab replay FILE` using a
  versioned, selector-stable command format suitable for review and editing.
- [ ] Add shell-level contract tests with `pytest` for exit status, stdout
  purity, stderr diagnostics, JSON Schema validation, request correlation,
  timeouts, signals, stale sessions, and paths containing spaces or Unicode.
  Run them under the existing `mypy` and branch-coverage checks.
- [ ] Add Hypothesis state machines for session lifecycle, cancellation,
  retries, stale cleanup, and record/replay once those stateful commands exist.
  Preserve every minimized failure as a deterministic regression test.
- [ ] Publish short copy-paste examples for discovery, one-shot inspection, a
  persistent resize gesture, capture, scenario execution, and cleanup.

## Harden the web inspector and HTTP API

The browser inspector is a human-facing adapter over the same command
dispatcher as the CLI. Keep HTTP and React concerns out of scenario and runtime
logic. Do not create a second operation model for the inspector.

- [ ] Pin `fastapi` and `uvicorn` as runtime dependencies. Replace the
  `ThreadingHTTPServer` implementation after parity tests cover asset serving,
  API routes, security headers, shutdown, and the existing session lock.
- [ ] Give each inspector session one worker that owns all viewer mutations.
  Queue mutating actions in request order and bound the queue. Run blocking
  viewer calls outside the ASGI event loop. Publish immutable read snapshots so
  HTTP readers do not share mutable viewer state.
- [ ] Put the inspector endpoints under `/api/v1`. Provide `GET /state`, `POST
  /actions`, `GET /events`, and `GET /captures/{version}` beneath that prefix.
  Route actions through the Pydantic command models used by the CLI and JSONL.
- [ ] Set route-specific request limits, response limits, and timeouts. Preserve
  the existing action-body limit. Reject oversized input before parsing it, and
  return a stable error when an output exceeds its inline limit.
- [ ] Generate and check in the OpenAPI document from the FastAPI routes and
  Pydantic models. Make `./xui-lab check` fail when the document is stale.
- [ ] Put the OpenAPI hash in both the server bootstrap response and the
  embedded client. Refuse actions when the hashes differ, and show the rebuild
  command in the inspector.
- [ ] Pin `openapi-typescript` as a frontend development dependency. Generate
  the route, request, response, event, and error types from the checked-in
  OpenAPI document. Delete the handwritten wire types that the generated types
  replace.
- [ ] Pin `openapi-fetch` and route inspector requests through one generated,
  typed client. Keep authentication, request IDs, timeouts, and error decoding
  in that client instead of React components.
- [ ] Pin `ajv` and validate every HTTP response and server event against the
  Pydantic-generated JSON Schemas before the frontend uses it. Convert valid
  wire values into UI models once. Do not add a parallel Zod schema.
- [ ] Return errors as
  [RFC 9457 Problem Details](https://www.rfc-editor.org/rfc/rfc9457.html) with
  stable XUI Lab fields for `code`, `requestId`, `operation`, retryability, and
  artifact paths. Do not expose FastAPI or Pydantic error formats.
- [ ] Keep the inspector on a random loopback port. Issue a random session token
  at startup and require it on every API request. Reject unexpected `Host` and
  `Origin` headers, and keep the token out of logs and artifacts.
- [ ] Resolve captures and artifacts through the current session manifest.
  Serve only files contained by that session's artifact directory. Never accept
  an arbitrary filesystem path from an HTTP request.
- [ ] Replace the 700 ms state polling loop with
  [Server-Sent Events](https://fastapi.tiangolo.com/tutorial/server-sent-events/).
  Send small events with event ID, request ID, state version, and artifact
  references. Refetch state after an invalidation event instead of streaming
  the complete tree. Keep actions as HTTP requests.
- [ ] Give SSE events monotonic IDs, heartbeats, and a bounded replay window.
  Resume from `Last-Event-ID`. If the requested event has expired or a client
  falls behind, require a full state refresh. Never let a slow client block the
  session worker or grow an unbounded buffer.
- [ ] Add `@tanstack/react-query` when the versioned API lands. Make it own
  server-state fetches, action invalidation, cancellation, and retry policy.
  Feed state-version events from SSE into query invalidation.
- [ ] Pin `httpx` as a development dependency. Test the real FastAPI ASGI app
  with `pytest` without opening a port. Cover validation, authentication,
  Problem Details, content types, security headers, SSE disconnects, and clean
  shutdown.
- [ ] Keep CORS disabled and disable FastAPI's Swagger UI and ReDoc routes in
  the shipped inspector. Test that logs omit session tokens and that shutdown
  closes every active request and SSE stream.
- [ ] Pin `@playwright/test` before the timeline and filmstrip work. Run it
  against the deterministic preview backend. Cover initial load, actions,
  reconnects, error display, capture changes, keyboard use, and failure traces.
- [ ] Enable `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes` for the
  inspector. Include generated types, schema validation, and Playwright tests
  in `npm run check --prefix inspector`.

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

## Complete inspection and failure diagnostics

- [ ] Verify that every tree node reports runtime class, XUI path, source file
  and line, local rectangle, screen rectangle, clipping rectangle, visibility
  chain, enabled chain, focus state, mouse-capture state, and hit-test order.
- [ ] Add overlap and text-clipping diagnostics based on production layout
  state.
- [ ] Record the scenario step, graphics environment, fixture, UI scale, fork,
  commit, and overlay state in every capture sidecar.
- [ ] Write an ordered capture manifest that links every automatic screenshot
  to its action, selector, sequence number, timestamp, tree, diagnostics,
  recording, and result or error.
- [ ] Add a scrubbable screenshot filmstrip modeled on Playwright UI Mode's
  [timeline view](https://playwright.dev/docs/test-ui-mode#timeline-view).
  Support pointer scrubbing, keyboard stepping, and jumping to the failed
  action.
- [ ] When a user scrubs to a historical screenshot, show the matching tree,
  selection, focus, recording, and diagnostics without mutating the live
  viewer. Clearly distinguish the live step from historical steps.
- [ ] Make locator and expectation failures include the smallest relevant tree
  excerpt instead of requiring the user to search the complete UI tree.

## Expand behavior coverage

- [ ] Prove shared selection across Inventory Explorer's tree, single-folder
  list, and grid views.
- [ ] Add tests for folder navigation, search, inspector details, and the
  holding tray.
- [ ] Add an accepted Inventory Explorer drag-and-drop case after the subject
  is declared.
- [ ] Keep structural assertions as the pass condition. Add platform-specific
  image comparisons only after the behaviors pass.

## Harden contracts and isolation

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
