# CLI examples

These examples use the pinned Alchemy checkout and the fetched local runtime.
Change both paths if you use another checkout or build.

```sh
SOURCE="$PWD/viewers/alchemy"
RUNTIME="$SOURCE/.gwigz/remote-artifacts/xui-lab"
```

## Discover subjects and operations

List subjects that the selected runtime can open:

```sh
./xui-lab --viewer-source alchemy="$SOURCE" \
  subjects --json --runtime "$RUNTIME" \
  --jq '.subjects[] | select(.openable) | .name'
```

Check an operation before you start a viewer:

```sh
./xui-lab --viewer-source alchemy="$SOURCE" \
  preflight --json --subject test_widgets --operation click \
  --runtime "$RUNTIME" \
  --jq '{fixture, operation: (.operations[] | select(.name=="click"))}'
```

## Inspect one session

Start a hidden 1200 by 800 viewer and retain its session ID:

```sh
SESSION=$(./xui-lab --viewer-source alchemy="$SOURCE" \
  session start test_widgets --runtime "$RUNTIME" --jq .sessionId)
```

Subjects can declare a default fixture. Inventory Explorer starts with its
fixture when `--fixture` is absent:

```sh
SESSION=$(./xui-lab --viewer-source alchemy="$SOURCE" \
  session start inventory_explorer --runtime "$RUNTIME" --jq .sessionId)
```

Read one control and its ranked selector:

```sh
./xui-lab get --session "$SESSION" \
  --path '/Floater View/floater_test_widgets/test_checkbox' \
  --jq .data.locator
```

## Resize through pointer input

Pick the bottom-right resize handle in the 1200 by 800 session. Then drag it 40
pixels right and 30 pixels down:

```sh
HANDLE=$(./xui-lab pick --session "$SESSION" \
  --x 1020 --y 150 --jq .data.control.control_id)

./xui-lab drag-by --session "$SESSION" \
  --control-id "$HANDLE" --dx 40 --dy -30 \
  --jq .data.handled
```

The command prints `true` when LLUI handles the gesture.

## Capture the result

Write a PNG and print its absolute path:

```sh
./xui-lab capture --session "$SESSION" \
  --name resized --jq .data.path
```

## Run a scenario

Run the documented scenario in its own viewer process:

```sh
./xui-lab --viewer-source alchemy="$SOURCE" \
  run tests/scenarios/readme_example.py \
  --runtime "$RUNTIME" --artifacts artifacts/readme-example
```

Run the same scenario as a layout gate. Captures record their frame's findings,
and any actionable finding makes the command exit with status `1`:

```sh
./xui-lab --viewer-source alchemy="$SOURCE" \
  run tests/scenarios/readme_example.py \
  --strict-layout-diagnostics \
  --runtime "$RUNTIME" --artifacts artifacts/readme-example
```

## Clean up

Close the session. Repeating this command is safe.

```sh
./xui-lab session close "$SESSION"
```

Remove every dead session record:

```sh
./xui-lab session status --jq '.sessions | length'
```
