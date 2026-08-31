# Alchemy adapter

This directory defines how `xui-lab` builds against Alchemy. The adapter has not
been implemented.

The adapter must use Alchemy's `.gwigz/*` scripts to configure and build the
viewer source. It must not maintain a second list of `indra/newview` source
files.

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

The pinned Alchemy submodule is the default source. Development commands must
also accept a local source override so an unpushed Alchemy branch can be tested.
