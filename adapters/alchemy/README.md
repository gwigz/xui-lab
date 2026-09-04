# Alchemy adapter

This directory defines how `xui-lab` builds against Alchemy. `adapter.json` is
the machine-readable capability contract. Each subject declares its required
capabilities and can name a default fixture by fixture ID.

[`EVENT_APIS.md`](EVENT_APIS.md) records the event APIs retained by the reusable
UI target and their no-login constraints.

The adapter joins Alchemy's supported CMake graph through `inject.cmake`. Pass
that file as `CMAKE_PROJECT_Alchemy_INCLUDE`. It defers this adapter until the
production viewer target exists. The adapter must not maintain a second list of
`indra/newview` source files.

The adapter reads the production target's source, link, source-directory,
binary-directory, and output-directory properties. It derives
`alchemy_newview_ui` from those values, retains registered subject controllers,
and excludes the platform application entry point and voice runtime.

Keep the lab build tree outside the viewer source and reuse it for the working
branch and configuration. The first build compiles the reduced production
runtime. Later adapter or fixture edits compile only the affected sources and
relink the lab. Cross-build-root compiler caches are optional and are not part
of the adapter contract.

The runtime side of the adapter must:

- Register the fork and its build metadata
- Initialize the real LLUI, LLXUI, rendering, skin, and floater systems
- Declare the viewer capabilities available to a scenario
- Populate real viewer models from deterministic fixtures
- Intercept unavailable external effects at their system boundaries
- Report a clear error when a subject needs an unavailable capability

The pinned Alchemy submodule is the default source. A local source override can
select an unpushed branch without changing the submodule pointer.

Pass the built executable to scenario or interactive commands with
`--runtime`. Build and artifact locations remain local environment choices.
