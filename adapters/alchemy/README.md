# Alchemy adapter

This directory defines how `xui-lab` builds against Alchemy. `adapter.json` is
the machine-readable capability contract.

[`EVENT_APIS.md`](EVENT_APIS.md) records the event APIs retained by the reusable
UI target and their no-login constraints.

The adapter joins Alchemy's supported CMake graph. It must not maintain a
second list of `indra/newview` source files.

Alchemy exposes its production newview source list and link settings through
`ALCHEMY_NEWVIEW_EXTENSION_DIRS`. The adapter derives `alchemy_newview_ui` from
that build graph. It retains registered subject controllers and excludes the
platform application entry point and voice runtime.

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
