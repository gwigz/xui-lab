# Alchemy adapter

This directory defines how `xui-lab` builds against Alchemy. `adapter.json` is
the machine-readable capability contract.

[`EVENT_APIS.md`](EVENT_APIS.md) records the event APIs retained by the reusable
UI target and their no-login constraints.

The adapter joins Alchemy's supported CMake graph. It must not maintain a
second list of `indra/newview` source files.

Alchemy must expose one reusable production UI target. That target must contain
the newview objects required to construct registered floaters while excluding
the platform application entry point. The adapter will link those objects into
a fork-specific build of `xui-lab`.

The runtime side of the adapter must:

- register the fork and its build metadata;
- initialize the real LLUI, LLXUI, rendering, skin, and floater systems;
- declare the viewer capabilities available to a scenario;
- populate real viewer models from deterministic fixtures;
- intercept unavailable external effects at their system boundaries; and
- report a clear error when a subject needs an unavailable capability.

The pinned Alchemy submodule is the default source. A local source override can
select an unpushed branch without changing the submodule pointer.

Pass the built executable to scenario or interactive commands with
`--runtime`. Build and artifact locations remain local environment choices.
