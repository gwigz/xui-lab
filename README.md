# xui-lab

`xui-lab` runs production LLUI and LLXUI controls without starting a full
viewer session. The Alchemy adapter provides the first runnable subject host
and a parent-controlled scenario runner.

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

## Check and format Python

xui-lab supports Python 3.10 and newer. Create a virtual environment and
install the pinned developer tools:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement requirements-dev.txt
```

Run the same lint and format checks as CI before the unit tests:

```sh
ruff check .
ruff format --check .
python -m unittest discover -s tests
```

Apply safe lint fixes before formatting:

```sh
ruff check --fix .
ruff format .
```

To run the optional Git hooks, install them in the current checkout:

```sh
pre-commit install
pre-commit run --all-files
```

Upgrade Ruff in a dedicated change. Update the version in `pyproject.toml`,
`requirements-dev.txt`, and `.pre-commit-config.yaml`, then reinstall the
developer tools. Run the fix commands above and inspect the complete diff
before committing the upgrade.

## Repository contents

- `AGENTS.md` defines the working rules for local and remote coding agents.
- `forks.json` lists the supported viewer forks and their build adapters.
- `schemas/forks.schema.json` defines the fork manifest format.
- `adapters/` contains the fork-specific build and runtime contracts.
- `viewers/` contains pinned viewer submodules.
- `fixtures/` contains deterministic viewer state.
- `scenarios/` contains interaction and regression scenarios.
- `SPEC.md` defines the first implementation.

Read `SPEC.md` before extending the executable. The implementation uses one
production-code test seam in Alchemy instead of compiling a copied list of
viewer source files.

## Use the Python API

The Python API opens one runtime process and exposes `Window` and `Locator`
objects. Locators identify controls by XUI path or model UUID. They resolve
against a fresh production view tree before every action and expectation.

```python
from pathlib import Path

from xui_lab import Capability, Lab, Viewport
from xui_lab.domain import parse_manifest
from xui_lab.io import read_json

root = Path.cwd()
manifest = parse_manifest(root, read_json(root / "forks.json"))
fork = manifest.forks[manifest.default_fork]
lab = Lab(
    root,
    fork,
    root / "viewers" / "alchemy",
    root / "viewers" / "alchemy" / ".gwigz" / "remote-artifacts" / "xui-lab",
    root / "artifacts",
)

with lab.open(
    artifact_id="python-test-floater",
    subject="test_widgets",
    viewport=Viewport(1024, 700, 1.0),
    capabilities=frozenset({Capability("input"), Capability("inspection")}),
) as window:
    checkbox = window.get_by_path(
        "/Floater View/floater_test_widgets/test_checkbox/CheckboxCtrl Button"
    )
    checkbox.expect_visible()
    checkbox.click().expect_handled()
    checkbox.expect_value(True)
```

Actions and expectations wait for stable tree state automatically. A timeout
reports the paths whose structural state changed. A locator that finds zero or
multiple controls reports the matching paths, runtime classes, and XUI source
locations. Failures retain the frame, UI tree, event trace, runtime diagnostics,
and runtime log under the artifact ID.

The current Alchemy runtime supports locator clicks, double-clicks, and
right-clicks. `fill()`, `press()`, `scroll()`, and `drag_to()` raise a capability
error until their production LLUI event paths are available. Use `Window.raw()`
to send an untyped command while developing an adapter.
