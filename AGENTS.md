# Working in xui-lab

## Start with the repository contract

Read `SPEC.md`, `forks.json`, and the selected fork adapter before changing
code. `README.md` describes the current commands and repository layout.

This repository is at the specification stage. It does not contain an
`xui-lab` executable yet. Do not report a viewer build as an `xui-lab` build.

Before editing, inspect both worktrees:

```sh
git status --short
git -C viewers/alchemy status --short
```

Existing changes belong to the user. Do not reset, revert, clean, or overwrite
them. Do not update an initialized submodule while its worktree is dirty.

Run the repository check before and after a coherent change:

```sh
python3 tools/check.py
```

## Select the viewer source explicitly

`forks.json` is the source of truth for supported forks, adapters, build
drivers, and resource roots. The pinned submodule is the default source.

Use a local override to work with an existing checkout or an unpushed branch:

```sh
python3 tools/check.py \
  --viewer-source alchemy=/absolute/path/to/alchemy
```

Carry the same source choice into configure, build, launch, and scenario
commands. Do not validate one checkout and build another.

Do not edit a detached submodule checkout for normal feature work. Make the
viewer change in a branch or worktree that belongs to that viewer repository.
Update the pinned submodule only when the task explicitly asks for a pointer
update. Keep the viewer commit and the submodule-pointer commit separate.

To add a fork, add one manifest entry, one pinned submodule, and one adapter.
Extend `tools/check.py` when the new fork introduces a manifest rule that all
future adapters must follow.

## Keep one production UI seam

Each fork builds its own `xui-lab` executable. Do not introduce a binary plugin
interface shared by incompatible forks.

The fork adapter must construct a real registered floater or panel in the lab's
root view. Input must travel through the normal LLUI event path. Inspection must
query the resulting production view tree.

Reuse the selected fork's LLUI, LLXUI, floater registry, models, filters,
bridges, menus, drag-and-drop handlers, rendering, fonts, colors, textures, and
shaders. Do not copy newview source lists into this repository. Do not create a
parallel inventory model or duplicate permission and action rules.

Replace login, network access, world state, URL launching, and file dialogs only
at their system boundaries. Record external effects for assertions. If a
subject needs an unavailable capability, fail with the capability name.

Run each scenario in a fresh process until tests prove that the selected viewer
can reset every relevant singleton and callback registry.

## Use the newest C++ supported by the selected fork

Read the selected fork's `CMAKE_CXX_STANDARD` before writing C++. Alchemy
currently requires C++20. Use C++20 language and library features in Alchemy
code when its supported compilers and standard libraries implement them. A fork
that enables a newer standard may use that standard in its adapter and binary.

Do not preserve C++11 or C++14 patterns in new code. Prefer standard-library
types and algorithms over local replacements. Useful C++20 tools include
`std::span`, `std::string_view`, `std::optional`, `std::variant`, scoped enums,
ranges, concepts, structured bindings, designated initializers, `constexpr`,
and `[[nodiscard]]`.

Use RAII and value semantics. A raw pointer may express a non-owning reference
when that matches the surrounding viewer API. Do not use raw `new` or `delete`
for ownership. Keep fork-specific ownership types such as `LLPointer` when the
production API requires them; do not wrap them in a second smart pointer.

Model finite states with scoped enums or variants instead of groups of Boolean
flags. Give semantically different identifiers different types when confusing
them would produce a valid but wrong call. Parse JSON, command-line values, and
environment variables once at the process boundary, then pass typed values.
Handle every state variant explicitly. Do not use a cast, nullable fallback, or
default branch only to silence the compiler.

Use `auto` when the initializer makes the type clear or when an iterator type
would obscure the operation. Spell out domain types when the type carries
meaning for the reader. Follow the selected fork's local formatting and naming
style in adapter code.

Do not raise a fork's global language level as a side effect of lab work. If a
needed standard feature is unavailable on one supported platform, either choose
an equally clear supported feature or make the language-level change a separate
viewer decision with its own build verification.

## Use the selected fork's build driver

Never assume that all forks use Alchemy's commands. Read the `buildDriver` and
the adapter contract for the selected fork. Do not bypass a supported driver
with raw CMake, Ninja, Xcode, or SSH commands.

Alchemy uses `.gwigz/remote-build` from the selected Alchemy checkout. Inspect
the resolved settings before a remote operation:

```sh
ALCH_REMOTE_ROOT=build/xui-lab-alchemy \
  .gwigz/remote-build info
```

Use a task-specific `ALCH_REMOTE_ROOT`. Never use an empty value, `/`, `.`,
`..`, `~`, or a root shared with another active checkout. The driver uses
`rsync --delete`; two runs against one remote root can corrupt each other's
source and build state. Do not run configure, build, or sync operations
concurrently against the same remote root.

After the Alchemy adapter adds the `xui-lab` target, use the driver for the full
remote cycle:

```sh
ALCH_REMOTE_ROOT=build/xui-lab-alchemy \
  .gwigz/remote-build all
ALCH_REMOTE_ROOT=build/xui-lab-alchemy \
  .gwigz/remote-build fetch
ALCH_REMOTE_ROOT=build/xui-lab-alchemy \
  .gwigz/remote-build verify
```

Use `build` instead of `all` only after the same remote root has a valid
configuration for the current source. Read `.gwigz/remote-build` before adding
new command-line assumptions. The driver currently synchronizes only the
Alchemy repository, so the adapter must add an explicit way to include the
outer `xui-lab` source. Do not copy files into the submodule as a workaround.

If SSH, host verification, Touch ID, or another user-presence check blocks the
driver, report the exact command and wait for the user. Do not replace keys,
weaken host verification, or change the user's SSH configuration.

Keep fetched applications, binaries, screenshots, event traces, UI trees, and
diagnostics out of Git. Store transient results in ignored build or artifact
directories.

## Build in verifiable stages

Keep the implementation sequence in `SPEC.md`. Each stage must finish with a
real behavior check before the next stage starts:

1. Expose the selected viewer's reusable production UI target and subject host.
2. Render one registered floater with production resources and capture a frame.
3. Add path-addressed input, UI-tree inspection, and control highlighting.
4. Load deterministic data into real viewer models.
5. Add scenario assertions and complete failure artifacts.

Do not implement broad service mocks before a chosen subject requires them.
When a new service is required, add one named capability to the adapter and one
scenario that proves its visible behavior.

Use structural assertions for behavior. Treat screenshots as secondary,
platform-specific evidence. A passing screenshot alone does not prove that an
event was handled, a menu opened, focus moved, or selection changed.

## Verify and hand off the work

At minimum, run:

```sh
python3 tools/check.py
python3 tools/check.py --viewer-source alchemy=/path/to/local/alchemy
```

Replace the example path with the checkout used for the work. If source or XUI
changed in a viewer fork, run that fork's adapter checks and supported build
driver. Exercise the affected behavior and inspect every generated artifact.

Before finishing, inspect the status of the superproject and every viewer
checkout touched by the task. Report the selected fork and commit, commands
run, behavior observed, artifact locations, and remaining placeholders.

Do not push commits, tags, submodule pointers, artifacts, or branches unless the
user explicitly asks for a push.
