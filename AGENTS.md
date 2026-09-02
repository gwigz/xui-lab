# Working in `xui-lab`

Read `AGENTS.local.md` when it exists. It contains ignored instructions for the
current machine.

## Protect repository state

Before changing code, read `SPEC.md`, `forks.json`, and the selected fork
adapter. `README.md` gives the current project status, and `TODO.md` tracks
unfinished work.

Inspect both worktrees before editing:

```sh
git status --short
git -C viewers/alchemy status --short
```

Existing changes belong to the user. Do not reset, revert, clean, or overwrite
them. Do not update an initialized submodule while its worktree is dirty.

Run the repository check before and after a coherent change. If the baseline
fails, record the failure and do not introduce another one.

```sh
./xui-lab check
```

## Use pinned tools

The project supports Python 3.10 and newer. Install the tools in
`requirements-dev.txt`. Use the pinned versions, not global or floating Ruff
and LLVM versions.

Apply safe Ruff fixes and formatting only to the Python files you changed. Run
the full checks before finishing a Python change:

```sh
ruff check .
ruff format --check .
python3 -m unittest discover -s tests
```

Do not enable Ruff preview rules or unsafe fixes. Upgrade Ruff in a dedicated
change, with matching versions in `pyproject.toml`, `requirements-dev.txt`, and
`.pre-commit-config.yaml`.

`xui-lab check` includes the Markdown style audit.

Before writing C++, read the selected fork's `CMAKE_CXX_STANDARD`. Alchemy uses
C++20. Follow the fork's local style, prefer standard-library types and RAII,
and preserve ownership types required by viewer APIs. Do not raise a fork's
language level as a side effect of lab work.

Format only adapter-owned C++ files with the pinned LLVM tools:

```sh
./xui-lab cpp format
./xui-lab cpp format --check
```

Run `clang-tidy` with the selected viewer build's `compile_commands.json`:

```sh
./xui-lab cpp tidy \
  --compile-commands /absolute/path/to/viewer-build/compile_commands.json
```

Run the lint command in the environment that owns the build tree. Do not pass
viewer-submodule files to `xui-lab cpp`.

## Use one viewer source

`forks.json` defines the supported forks, adapters, build drivers, and resource
roots. The pinned submodule is the default source. To use another checkout,
pass an explicit override:

```sh
./xui-lab \
  --viewer-source alchemy=/absolute/path/to/alchemy \
  check
```

Use the same source for checks, configure, build, launch, and scenarios. Do not
validate one checkout and build another. Keep machine-specific build, sync, and
artifact commands in ignored local instructions.

Do not edit a detached submodule checkout for normal feature work. Make viewer
changes in a branch or worktree owned by that repository. Update the pinned
submodule only when the task requests it, and keep the viewer commit separate
from the pointer update.

To add a fork, add one manifest entry, one pinned submodule, and one adapter.
Extend `xui-lab check` only for rules that every future adapter must follow.

Build through the selected fork's supported graph. Do not copy its source list.
Keep binaries, screenshots, traces, UI trees, and diagnostics in ignored build
or artifact directories. Do not report a viewer build as an `xui-lab` build.

## Preserve the production UI path

Each fork builds its own `xui-lab` executable. Do not add a binary plugin
interface between incompatible forks.

The adapter must create a real registered floater or panel in the lab root
view. Send input through normal LLUI events and inspect the resulting production
view tree. Reuse the fork's UI systems, models, action rules, rendering, and
resources. Do not create parallel models or duplicate production rules.

Replace login, network access, world state, URL launching, and file dialogs only
at system boundaries. Record external effects for assertions. When a subject
needs a new service, add one named capability and one scenario that proves its
visible behavior. Fail with the capability name when the service is unavailable.

Run each scenario in a fresh process until tests prove that the fork can reset
its singletons and callback registries. Use structural assertions as the pass
condition. Screenshots are secondary evidence and do not prove event handling,
focus, menus, or selection.

## Verify and hand off

Run `./xui-lab check` against the pinned source. If the work used a local
checkout, run it again with the same `--viewer-source` override. If viewer
source or XUI changed, run the adapter checks and the fork's supported build
workflow. Exercise the affected behavior and inspect every generated artifact.

Before finishing, inspect the status of the superproject and every viewer
checkout touched by the task. Report the selected fork and commit, commands
run, observed behavior, artifact locations, and remaining placeholders.

Write every commit in Commitizen-compatible Conventional Commits format:
`type(scope): summary` or `type: summary`. Use the established `feat`, `fix`,
`docs`, `build`, and `chore` types. Mark breaking changes with `!` and add a
`BREAKING CHANGE:` footer.

Do not push commits, tags, submodule pointers, artifacts, or branches unless the
user explicitly asks for a push.
