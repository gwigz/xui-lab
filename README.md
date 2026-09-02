# `xui-lab`

> [!CAUTION]
> `xui-lab` is unfinished and changes often.

`xui-lab` runs production Alchemy `LLFloater` subclasses and their C++
controllers without a full viewer session. It loads XUI through production
floater code, sends normal LLUI events, and uses real viewer models. A reduced
runtime replaces login, networking, world simulation, and other external
services at explicit boundaries.

## What exists

- A Python API for input, structural assertions, UI inspection, and failure
  artifacts.
- A headed inspector for picking controls, reloading XUI, resizing subjects,
  and replaying scenarios.
- Hidden scenario runs through the same production UI path.

> [!WARNING]
> Only the Alchemy adapter and its `test_widgets` subject are usable today.
> Scrolling and drag-and-drop are not wired up.

## Build performance

Debug arm64 timings from an Apple M2 Ultra on 2 September 2026:

| Workload | Ninja actions | Wall time |
| --- | ---: | ---: |
| Initial `xui-lab` target | 1,285 | 181.99 s |
| Full `alchemy-bin` target | 788 | 287.52 s |
| Lab commit-metadata rebuild | 7 | 14.00 s |
| One adapter source compile and relink | 2 | 6.94 s |
| No-op lab build and source sync | 0 | 5.65 s |

Dependencies were already installed, and the viewer reused dependency targets
built for the lab. A persistent build tree reduces an adapter edit to one
compile and one link.

For design and build details, read [`SPEC.md`](SPEC.md),
[`forks.json`](forks.json), and the
[`Alchemy adapter contract`](adapters/alchemy/README.md).
