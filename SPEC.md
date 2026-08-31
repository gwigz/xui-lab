# xui-lab specification

## Problem Statement

Viewer developers need to start and log in to a full viewer to test most LLUI
and LLXUI changes. That cycle is slow, and world state makes failures difficult
to reproduce. The existing XUI preview can display layouts, but it does not
consistently instantiate the registered controller classes that supply real
floater behavior.

These limits make ordinary UI defects expensive to diagnose. A clipped label,
a pane that stops at the wrong height, or a context menu that never opens can
survive until someone builds the viewer and exercises the exact state by hand.
The current Inventory Explorer work has examples of each class of defect.

A useful tool must run production UI code. A parallel widget model or copied
inventory rules would produce convincing screenshots while missing the defects
that matter. The tool must also accommodate viewer forks whose build systems,
global services, and registered controls have diverged.

## Solution

Build `xui-lab` as a separate executable in a repository that pins supported
viewer forks as Git submodules. Compile one fork-specific `xui-lab` binary
against each selected fork. Do not define a binary ABI across forks.

Each fork supplies one adapter that exposes its production UI runtime to the
lab. The adapter initializes LLUI, LLXUI, rendering, skins, menus, and registered
floaters without starting login, networking, world simulation, or scene
rendering. It loads deterministic fixtures into real viewer models and replaces
external effects only at system boundaries.

The lab has an interactive mode for visual work and a scenario mode for
repeatable tests. Both modes use the same subject host, input path, inspection
API, and renderer. A scenario can resize a floater, click a control, type text,
open a context menu, inspect the UI tree, assert visible behavior, and capture a
frame with its diagnostics.

The first adapter targets Alchemy. Developers can use the pinned Alchemy
submodule or select a local checkout. The local override supports unpushed
branches without changing the submodule commit.

## User Stories

1. As a viewer developer, I want to open a registered floater without logging in, so that I can test UI changes in a short feedback cycle.
2. As a viewer developer, I want the lab to compile against production viewer code, so that the lab exercises the code users run.
3. As a viewer developer, I want to select a supported viewer fork, so that I can test the same XUI concept against different viewers.
4. As a viewer maintainer, I want each fork build to pin an exact commit, so that a failed scenario can be reproduced later.
5. As a viewer developer, I want to select a local viewer checkout, so that I can test a branch before I push it.
6. As an Alchemy developer, I want the adapter to use the `.gwigz/*` build scripts, so that lab builds follow the supported local build process.
7. As a fork maintainer, I want one documented adapter contract, so that I can add support without changing the lab core.
8. As a fork maintainer, I want adapter capability declarations, so that unsupported scenarios fail with a specific reason.
9. As a UI developer, I want the lab to load XUI from the source checkout, so that I can inspect an edit without packaging a viewer.
10. As a UI developer, I want XUI hot reload in interactive mode, so that I can compare layout changes without restarting the lab.
11. As a UI developer, I want a visible SDL window, so that I can use the mouse and keyboard as I would in the viewer.
12. As a test runner, I want a hidden OpenGL window, so that scenarios can render frames without a visible application window.
13. As a UI developer, I want the production UI shaders, fonts, colors, and textures, so that captured frames match the viewer closely.
14. As a UI developer, I want to resize the subject to exact dimensions, so that I can reproduce clipping and layout faults.
15. As a UI developer, I want to inspect the control under the pointer, so that I can identify the control responsible for a visible defect.
16. As a UI developer, I want to see the selected control's XUI path and runtime class, so that I can find its declaration and controller.
17. As a UI developer, I want to see the selected control's source file and line, so that I can open the relevant XUI declaration.
18. As a UI developer, I want to see local, screen, and clipping rectangles, so that I can explain truncated or overlapping content.
19. As a UI developer, I want to see visibility and enabled-state chains, so that I can find the ancestor that suppresses a control.
20. As a UI developer, I want to see keyboard focus and mouse capture, so that I can diagnose input routed to the wrong control.
21. As a UI developer, I want the lab to outline a selected control, so that I can connect inspector data to the rendered frame.
22. As a UI developer, I want overlap and text-clipping diagnostics, so that the lab can point out common layout defects.
23. As a scenario author, I want to address controls by XUI path, so that tests do not depend on screen coordinates alone.
24. As a scenario author, I want to target model objects by stable identifiers, so that inventory tests remain valid when layout changes.
25. As a scenario author, I want to send normal mouse and keyboard events, so that tests use production event dispatch.
26. As a scenario author, I want to assert whether an input event was handled, so that a swallowed context-menu event is visible in test output.
27. As a scenario author, I want to inspect visible popup menus, so that I can test both menu creation and menu contents.
28. As a scenario author, I want fixed viewer fixtures, so that a scenario sees the same folders, items, names, and avatar state on every run.
29. As an inventory developer, I want fixtures loaded into the real inventory model, so that filters, bridges, permissions, and actions keep their production rules.
30. As an inventory developer, I want tree, single-folder list, and grid views to share real selection state, so that the lab can catch selection synchronization faults.
31. As an inventory developer, I want to test drag and drop through the production handler, so that the lab does not copy acceptance rules.
32. As a scenario author, I want external effects recorded instead of executed, so that I can assert an attempted URL, file dialog, or network action safely.
33. As a scenario author, I want each scenario to start in a fresh process, so that globals from an earlier scenario cannot change the result.
34. As a scenario author, I want to advance an exact number of frames, so that animations and deferred layout do not require arbitrary sleeps.
35. As a scenario author, I want the lab to detect a stable UI tree, so that captures occur after layout has settled.
36. As a test reviewer, I want each failure to include a frame, UI tree, event trace, and diagnostics, so that I can investigate it without rerunning the test first.
37. As a test reviewer, I want structural assertions to be independent of pixels, so that font and driver differences do not hide behavior regressions.
38. As a test reviewer, I want platform-specific image comparisons, so that genuine rendering changes remain reviewable without requiring identical cross-platform rasterization.
39. As a CI maintainer, I want a nonzero exit status for failed assertions or missing capabilities, so that the build reports a failed scenario.
40. As a CI maintainer, I want scenarios to run without network access, so that service availability cannot make the suite intermittent.
41. As a viewer maintainer, I want the lab to avoid a copied list of newview source files, so that new production dependencies cannot bypass the supported build graph.
42. As a viewer maintainer, I want the lab core to avoid fork-specific globals, so that a new fork changes its adapter rather than every scenario.
43. As a viewer developer, I want the binary to report the fork name and commit, so that every artifact identifies the code under test.
44. As a UI developer, I want the inspector hidden during normal captures, so that inspection tools do not alter the subject image.
45. As a UI developer, I want to reload a scenario after editing XUI, so that the lab supports both exploration and regression testing.

## Implementation Decisions

- `xui-lab` is a separate executable and repository. The repository is a
  superproject that pins supported viewer forks as submodules.
- Each supported fork produces its own `xui-lab` binary. The project does not
  define a stable binary interface between different viewer forks.
- A versioned manifest assigns each fork a stable identifier, source, adapter,
  build driver, and resource root. Commands may override the source for one
  invocation without modifying the manifest.
- The lab core owns scenario parsing, process control, assertions, inspection
  commands, and artifact naming. Fork adapters own viewer initialization,
  production target selection, model fixture loading, and external-effect
  interception.
- The project uses one high-level test seam. A fork adapter creates a real
  registered floater or panel inside a lab-owned root view, and the lab drives
  that subject through normal LLUI events. Lower-level mocks do not bypass that
  seam.
- Each fork exposes a reusable production UI build target. The target includes
  the required viewer controller objects and excludes the normal application
  entry point. The lab does not scrape or copy the fork's source list.
- The Alchemy adapter configures and builds through `.gwigz/*`. The adapter does
  not introduce a second raw CMake workflow for Alchemy.
- The runtime uses a visible SDL OpenGL window in interactive mode and a hidden
  SDL OpenGL window in scenario mode. Both modes use the same renderer.
- The runtime loads the production UI shader set. It also loads the selected
  fork's fonts, named colors, XUI, and skin textures from the chosen source.
- The initial texture provider reads local skin assets synchronously. A scenario
  does not start the viewer texture-fetch service.
- The runtime constructs the normal root view, floater view, menu holder, focus
  manager integration, tooltip host, and popup routing required by a subject.
  It does not construct the world view or scene-rendering pipeline.
- A subject declares its required capabilities. Initial capabilities include
  inventory model state, agent identity, avatar state, cached avatar names, and
  external-effect recording. The adapter reports missing capabilities before it
  opens the subject.
- Fixtures populate production models with deterministic identifiers and data.
  Fixtures do not implement viewer models, filters, bridge rules, permissions,
  or actions.
- External effects stop at explicit system boundaries. The lab records the
  request and returns a declared result. Internal action eligibility and routing
  remain production code.
- Each scenario runs in a fresh process during the first implementation. The
  project will not claim that viewer singletons can reset until tests prove a
  complete reset boundary.
- Scenario files and command messages use JSON. The runtime may translate JSON
  to LLSD after it validates the input.
- The interactive controller and scenario runner use the same command set. The
  command set covers loading, resizing, querying, picking, input, frame
  advancement, capture, reload, and shutdown.
- The inspector extends the existing view information with source provenance,
  clipping, focus, mouse capture, layout state, hit-test order, and event
  results. The first version exposes JSON output and an optional draw overlay.
- The first version does not add a permanent native inspector pane. Keeping the
  inspector outside the subject prevents the tool from changing layout results.
- Frame stabilization compares observable UI tree and layout state across
  consecutive frames. Scenarios do not use fixed-duration sleeps as their main
  readiness condition.
- Each capture records the fork identifier, fork commit, viewport, UI scale,
  fixture, scenario step, and graphics environment.
- Scenario artifacts consist of a rendered frame, a UI tree, an event trace,
  and diagnostics. The runner writes all artifacts before it exits after a
  failure.

## Testing Decisions

- Tests exercise the highest available behavior seam. A test opens the real
  registered subject, sends normal input, and inspects visible results.
- Structural assertions are the primary pass condition. They cover control
  state, rectangles, selection, focus, menus, events, and recorded effects.
- Image comparisons are secondary. Baselines are platform-specific and use a
  declared tolerance because font and graphics-driver rasterization can differ.
- The runner tests manifest parsing and scenario parsing as process boundaries.
  Internal scenario data uses validated types and does not repeat boundary
  checks.
- Adapter contract tests verify fork identity, capability reporting, resource
  discovery, production subject registration, and clean failure for an
  unavailable capability.
- Runtime tests verify visible and hidden rendering, exact viewport resizing,
  XUI-path input, focus changes, mouse capture, popup routing, frame capture, and
  clean process shutdown.
- Inspector tests verify UI-tree queries, source provenance, clipping
  calculations, hit-test order, overlay exclusion, and event traces.
- Fixture tests verify stable identifiers and prove that the selected fork's
  real model receives the fixture data.
- Alchemy already has useful prior art: a hidden SDL OpenGL test context with
  framebuffer readback, a stateful headless window, path-addressable window
  events, view-tree information, and an XUI preview with control highlighting
  and overlap detection. The adapter should extract or reuse those seams.
- The first Inventory Explorer regression right-clicks a known inventory item.
  The test asserts that the event is handled, a popup becomes visible, and the
  production bridge supplies the expected enabled and disabled entries.
- The second Inventory Explorer regression opens the empty inspector at several
  widths. The test asserts that its text stays inside the effective clipping
  rectangle and captures each width.
- Later Inventory Explorer scenarios cover tree, single-folder list, grid,
  folder navigation, shared selection, search, inspector details, the holding
  tray, and drag and drop.
- CI runs scenarios without network access. A scenario that requests an
  undeclared service fails instead of contacting the service.

## Out of Scope

- The first implementation does not start login, region connectivity, world
  simulation, voice, media, or scene rendering.
- The project does not provide one executable that loads binary plugins from
  incompatible viewer forks.
- The project does not reproduce viewer models or permission rules inside the
  lab core.
- The first implementation does not support every floater. It adds capabilities
  only when a selected subject needs them.
- The first implementation does not promise identical image output across
  operating systems, graphics drivers, or font-rendering libraries.
- The first implementation does not replace focused unit tests for layout
  algorithms, filters, models, or parsers.
- The first implementation does not provide a browser-based inspector or a
  remote hosted service.
- The first implementation does not publish or package `xui-lab` for end users.

## Further Notes

Implementation should proceed in checked stages. First, render one existing
Alchemy test floater with production resources. Next, add input and inspection.
Then add the inventory fixture capability and open Inventory Explorer. Add the
scenario runner only after those interactive operations work through one command
set.

The first Alchemy change should expose the reusable production target and the
single subject-host seam. That change should remain separate from Inventory
Explorer fixes so other UI work can use the lab.

The requested to-spec workflow normally publishes this specification to a
configured issue tracker and applies the `ready-for-agent` label. This workspace
does not provide an issue tracker or its label vocabulary, so this version is
stored in the repository and has not been published. Configure the workflow's
issue-tracker integration before requesting publication.

The project needs a license decision before it distributes binaries or accepts
code from viewer forks with different licensing terms.
