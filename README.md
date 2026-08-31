# xui-lab

`xui-lab` will run production LLUI and LLXUI controls without starting a full
viewer session. It is currently a specification-stage repository. The binary
has not been implemented.

The repository pins supported viewer forks as Git submodules. A local source
override can select an existing checkout, including a branch that has not been
pushed.

## Check the repository

Initialize the pinned viewers after cloning:

```sh
git submodule update --init --recursive
```

Check the manifest, adapters, submodules, and specification:

```sh
python3 tools/check.py
```

Check an unpushed Alchemy checkout instead of the pinned submodule:

```sh
python3 tools/check.py \
  --viewer-source alchemy=/Users/private/Workspace/fun/alchemy
```

The override changes only the current command. It does not modify the manifest
or the submodule commit.

## Repository contents

- `forks.json` lists the supported viewer forks and their build adapters.
- `schemas/forks.schema.json` defines the fork manifest format.
- `adapters/` contains the fork-specific build and runtime contracts.
- `viewers/` contains pinned viewer submodules.
- `fixtures/` will contain deterministic viewer state.
- `scenarios/` will contain interaction and regression scenarios.
- `SPEC.md` defines the first implementation.

Read `SPEC.md` before adding the executable. The first implementation must add
one production-code test seam to Alchemy rather than compile a copied list of
viewer source files.
