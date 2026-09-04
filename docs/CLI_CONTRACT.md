# CLI contract

This reference defines version 1 of the XUI Lab command-line contract. Machine
records use `schemaVersion: 1`. The schemas returned by `xui-lab schema` are the
normative field definitions.

The contract follows the stream and exit-status rules in the
[Command Line Interface Guidelines](https://clig.dev/). Its discovery output
follows the field-selection approach of
[GitHub CLI JSON output](https://cli.github.com/manual/gh_help_formatting).
JSONL sessions use the record framing of
[`codex exec`](https://github.com/openai/codex/blob/main/codex-rs/exec/src/cli.rs).

## Output streams

Commands in JSON mode write one UTF-8 JSON document and one trailing newline to
standard output. JSONL mode writes one complete JSON record per line. These
modes do not write headings, prompts, progress animation, color, or
terminal-specific text to standard output.

Human-readable command results also use standard output. Diagnostics, warnings,
and errors that occur before the CLI accepts a structured request use standard
error. After the CLI accepts a JSON command, a failure writes one `ErrorRecord`
to standard output. Diagnostic text can accompany that record on standard
error. JSON success documents contain no diagnostic prose.

## Discovery commands

`subjects --json` lists adapter-declared subjects, required capabilities,
default fixtures, the selected viewer source, and whether a `--runtime` binary
can open each subject. `operations --json` lists query and input operations.
`preflight --json` reports capability and fixture availability. It suggests
valid operations when a capability is missing. `schema` prints the generated
JSON Schema catalog. These commands write one JSON document and do not start a
viewer session.

```sh
./xui-lab --request-id req_discover subjects --json
./xui-lab --request-id req_preflight preflight --json \
  --subject test_widgets --operation dragAndDrop
./xui-lab --viewer-source alchemy=/path/to/alchemy subjects --json \
  --runtime /path/to/xui-lab
```

Omit `--runtime` to inspect declarations without probing a binary. When
`--runtime` is present, a subject is openable only if the binary matches the
selected source and its default fixture is available. JSON commands do not
print color, prompts, or progress animation. Pass `--request-id` before the
subcommand, or the CLI generates one and copies it into the JSON document.
`--jq` filters these documents the same way it filters session output.

## Sessions and one-shot commands

`session start SUBJECT --runtime PATH` starts a hidden viewer process, binds a
user-local Unix socket under `platformdirs`, and writes a session id, PIDs,
fork commit, subject, viewport, and capabilities to stdout. `--artifacts`
defaults to a user-temp directory (`XUI_LAB_ARTIFACTS_DIR` overrides it) so
session and test runs do not write into the checkout. Pass an explicit path
when you want to keep the files. A subject's declared default fixture loads
when `--fixture` is absent. Pass `--fixture PATH` to override the default.
`session status` and `session close` inspect or stop that process. Close is
idempotent and reports whether a process was terminated. Dead PIDs are removed
on status and close. `--dry-run` on `session close`, `reload`, and `run` shows
the session, subject, or artifact directory that would change without
reloading, pruning, or terminating. Input gestures do not accept `--dry-run`.

`session jsonl SESSION_ID` reads one typed CLI command per stdin line and
writes one result or `ErrorRecord` per stdout line. One-shot commands such as
`tree`, `get`, `click`, `fill`, `press`, `scroll`, `drag-by`, `drag-to`,
`pick`, `resize-viewport`, `resize-subject`, `capture`, `reload`, and
`diagnostics` send the same models over that socket. They require `--session`.
Selector flags are `--control-id`, `--model-id`, `--path`, `--role`, `--label`,
`--placeholder`, and `--text`. Conflicting selector flags are rejected at
parse time.

Every entry point converts selectors to `selector.schema.json`. The selector is
a versioned discriminated union. Generated selectors rank a role and accessible
name first, followed by a label, placeholder, visible text, and model ID. A
control ID is the final identity fallback. An XUI path records provenance and
is used only when the control has no runtime identity.

`tree` and `get` return a concise excerpt by default and write the full tree
to an artifact with path, size, and hash. `--include-tree` inlines the full
tree and prints a size warning on stderr. `--fields` projects dotted keys
from one-shot `data`. `--jq EXPR` runs a jq program on the JSON document
that would have been printed. String results are raw, without quotes, so
`--jq .sessionId` can be captured into a shell variable. Multiple results
are written one per line. `--jq` does not rewrite `ErrorRecord` output.
An invalid expression fails with status `2` before the command runs.
`--timeout` bounds session startup, socket waits, and runtime requests.
Capture results return file paths, never image bytes. Each capture sidecar
includes the actionable layout diagnostics collected for that frame.

`diagnostics` enriches each actionable layout finding with its control path,
source location, local, screen, and clipping rectangles, and ancestor chain.
It suppresses generated child overflow, intentionally offscreen scroll
content, and lab host-root overlap. `layout.actionableCount` is the stable
summary for automation. Python scenarios can call
`Window.expect_no_layout_diagnostics()` directly. Pass `path_prefix="/…"` to
limit an assertion to one production subtree.

Pass `--strict-layout-diagnostics` to `run` to fail on the first captured frame
with actionable findings and to check once more when the scenario finishes.
The failing capture and its sidecar remain available in the scenario artifact
directory.

`record --session SESSION_ID --output FILE` reads the runtime's input history
and current production tree. It ranks each transient control ID into the same
selector contract used by one-shot commands, then writes a versioned recording
that contains no session or request IDs. `replay FILE --session SESSION_ID`
validates the complete file before sending its commands in order. Each replayed
command receives the replay request ID plus a one-based sequence suffix. Replay
stops at the first error and leaves earlier result records valid.

```sh
./xui-lab session start test_widgets --runtime /path/to/xui-lab --jq .sessionId
./xui-lab tree --session sess_abc --jq .data.tree.control_id
./xui-lab click --session sess_abc --control-id ok
./xui-lab record --session sess_abc --output actions.json
./xui-lab replay actions.json --session sess_fresh
./xui-lab session close sess_abc
```

## Exit statuses

The CLI assigns these statuses:

| Status | Meaning |
| ---: | --- |
| `0` | Every requested operation succeeded. |
| `1` | The CLI accepted the request, but an operation or scenario failed. |
| `2` | The arguments, configuration, or boundary data were invalid. |
| `128 + N` | Signal `N` terminated the process. |

For a multi-operation command, any failed operation makes the command exit with
status `1`. Records written before the failure remain valid.

## Error records

Machine errors use the `ErrorRecord` schema. Consumers select behavior from
`code`, not `message`. Version 1 defines these codes:

| Code | Meaning |
| --- | --- |
| `invalid_input` | A command value failed public input validation. |
| `invalid_<boundary>` | Data failed the named Pydantic boundary contract. |
| `missing_capability` | The subject cannot provide a required capability. |
| `assertion_failed` | Observed production UI state did not match an assertion. |
| `runtime_failure` | The viewer runtime failed or broke its protocol. |
| `scenario_failure` | Scenario code raised another exception. |

Every error record includes `operation` and `retryable`. It includes
`requestId`, `selector`, `capability`, and artifact paths when those values are
known.

A record that failed a Pydantic boundary contract also carries `details`: one
line per rejected field, naming the field and what it needs, such as
`selector.path must match '^/'`. The `message` field repeats the first two of
those lines. Both are for people. Code branches on `code`.

## Request IDs and timestamps

Commands accept or generate a non-empty request ID. Results, progress events,
errors, and artifact manifests copy that ID without modification.

A record that includes time uses a `timestamp` field. The value is an RFC 3339
UTC timestamp with a `Z` suffix, for example `2026-09-03T10:15:30.123456Z`.
Timestamps describe when XUI Lab observed or completed an event. Consumers must
use sequence fields, not wall-clock time, to order records from one session.

## Compatibility

The meaning of an existing field, operation, error code, or exit status does
not change within schema version 1. The following additions are compatible:

- A new command or operation
- A new error code
- A new optional field
- A new enum value where the schema permits extension

Consumers must ignore unknown optional fields and handle unknown operations or
error codes as unsupported values. Removing or renaming a field, changing its
type, making an optional field required, or changing existing behavior requires
a new `schemaVersion`.
