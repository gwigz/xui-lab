# Working in xui-lab

Read `AGENTS.local.md` when it exists. It contains ignored instructions for the
current machine.

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

## Use the pinned Python tools

xui-lab supports Python 3.10 and newer. Install the developer tools from
`requirements-dev.txt`. Do not use a global or floating Ruff version to decide
the repository's lint or format output.

For Python changes, apply safe lint fixes before formatting:

```sh
ruff check --fix .
ruff format .
```

Before finishing a Python change, run the authoritative checks in this order:

```sh
ruff check .
ruff format --check .
python3 -m unittest discover -s tests
```

CI runs the same commands and remains authoritative. The pre-commit hooks are
optional. Do not enable Ruff preview rules or unsafe fixes.

Upgrade Ruff in a dedicated change. Update `pyproject.toml`,
`requirements-dev.txt`, and `.pre-commit-config.yaml` to the same version, then
inspect the lint and format diff before committing it.

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

Install the pinned LLVM tools from `requirements-dev.txt`. Format only the
adapter-owned C++ files:

```sh
python3 tools/cpp_quality.py format --check
python3 tools/cpp_quality.py format
```

Run `clang-tidy` with `compile_commands.json` from the selected viewer build:

```sh
python3 tools/cpp_quality.py tidy \
  --compile-commands /absolute/path/to/viewer-build/compile_commands.json
```

Run the lint command in the environment that owns the build tree. Do not pass
viewer-submodule files to `tools/cpp_quality.py`. The tool must reject paths
outside `adapters/`.

Do not raise a fork's global language level as a side effect of lab work. If a
needed standard feature is unavailable on one supported platform, either choose
an equally clear supported feature or make the language-level change a separate
viewer decision with its own build verification.

## Use the selected fork's build graph

Read the adapter contract before building. Do not bypass a fork's supported
build graph with a copied source list. Keep machine-specific build, sync, and
artifact commands in ignored local instructions.

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
changed in a viewer fork, run that fork's adapter checks and supported local
build workflow. Exercise the affected behavior and inspect every generated
artifact.

Before finishing, inspect the status of the superproject and every viewer
checkout touched by the task. Report the selected fork and commit, commands
run, behavior observed, artifact locations, and remaining placeholders.

Do not push commits, tags, submodule pointers, artifacts, or branches unless the
user explicitly asks for a push.
