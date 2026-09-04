"""Command-line entry point for xui-lab."""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

from .api import Lab, artifact_directory, default_artifact_root
from .contracts import (
    SCHEMA_VERSION,
    AdapterContract,
    CaptureCliCommand,
    CheckCliCommand,
    ClickCliCommand,
    CliCommand,
    CliCommandBase,
    ContractModel,
    CppFormatCliCommand,
    CppTidyCliCommand,
    DiagnosticsCliCommand,
    DragByCliCommand,
    DragToCliCommand,
    FillCliCommand,
    GetCliCommand,
    InteractiveCliCommand,
    OperationsCliCommand,
    PickCliCommand,
    PreflightCliCommand,
    PressCliCommand,
    RecordCliCommand,
    ReloadCliCommand,
    ReplayCliCommand,
    ResizeSubjectCliCommand,
    ResizeViewportCliCommand,
    RunCliCommand,
    SchemaCatalogContract,
    SchemaCliCommand,
    ScrollCliCommand,
    SessionCloseCliCommand,
    SessionJsonlCliCommand,
    SessionServeCliCommand,
    SessionStartCliCommand,
    SessionStatusCliCommand,
    SubjectsCliCommand,
    TreeCliCommand,
    error_record,
    parse_adapter,
    parse_cli_command,
    schema_documents,
)
from .cpp_quality import format_cpp, tidy_cpp
from .discovery import operations_contract, preflight_contract, subjects_contract
from .domain import Capability, Fork, ForkId, Manifest, Viewport
from .errors import InputError, XUILabError
from .fixtures import discover_fixtures, resolve_fixture
from .inspector_http import serve_inspector
from .interactive import (
    InteractiveConfig,
    InteractiveSession,
)
from .io import parse_manifest, parse_source_overrides, read_json, resolved_source
from .json_output import compile_jq, emit_json_document
from .recording import record_session, replay_file
from .repository import check_repository
from .scenarios import discover_scenarios, load_scenario
from .session_cli import (
    cmd_session_bound,
    cmd_session_close,
    cmd_session_jsonl,
    cmd_session_serve,
    cmd_session_start,
    cmd_session_status,
)

ROOT = Path(__file__).resolve().parents[1]
JSON_COMMANDS = frozenset(
    {
        "operations",
        "preflight",
        "schema",
        "subjects",
        "session",
        "tree",
        "pick",
        "get",
        "click",
        "fill",
        "press",
        "scroll",
        "drag-by",
        "drag-to",
        "resize-viewport",
        "resize-subject",
        "capture",
        "reload",
        "diagnostics",
        "record",
        "replay",
    }
)


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex


def emit_json(
    model: ContractModel, *, exclude_none: bool = False, jq: str | None = None
) -> None:
    emit_json_document(
        model.model_dump(mode="json", by_alias=True, exclude_none=exclude_none),
        jq,
    )


def optional_runtime(explicit: str | None) -> Path | None:
    if explicit is None:
        return None
    runtime = Path(explicit).expanduser().resolve()
    if not runtime.is_file():
        raise InputError(f"runtime executable not found: {runtime}")
    return runtime


def writes_json(command: CliCommand) -> bool:
    return command.command in JSON_COMMANDS


def json_operation_from_argv(argv: list[str] | None) -> str | None:
    values = list(sys.argv[1:] if argv is None else argv)
    names = [value for value in values if value in JSON_COMMANDS]
    if not names:
        return None
    operation = names[-1]
    if operation in {"operations", "preflight", "subjects"} and "--json" not in values:
        return None
    return operation


def request_id_from_argv(argv: list[str] | None) -> str:
    values = list(sys.argv[1:] if argv is None else argv)
    try:
        index = values.index("--request-id")
    except ValueError:
        return new_request_id()
    if index + 1 < len(values) and not values[index + 1].startswith("-"):
        candidate = values[index + 1]
        if candidate:
            return candidate
    return new_request_id()


def report_error(
    error: XUILabError,
    *,
    operation: str,
    request_id: str,
    json_output: bool,
) -> int:
    print(f"xui-lab: {error}", file=sys.stderr)
    if json_output:
        emit_json(
            error_record(error, operation=operation, request_id=request_id),
            exclude_none=True,
        )
    return 2 if isinstance(error, InputError) else 1


def load_manifest() -> Manifest:
    return parse_manifest(ROOT, read_json(ROOT / "forks.json"))


def select_fork(command: CliCommandBase) -> tuple[Fork, Path]:
    manifest = load_manifest()
    fork_id = ForkId(command.fork or manifest.default_fork)
    try:
        fork = manifest.forks[fork_id]
    except KeyError as error:
        raise InputError(f"unknown fork: {fork_id}") from error
    overrides = parse_source_overrides(command.viewer_source, manifest)
    return fork, resolved_source(fork, overrides)


def adapter_config(fork: Fork) -> AdapterContract:
    return parse_adapter(read_json(fork.adapter / "adapter.json"))


def runtime_path(_fork: Fork, _source: Path, explicit: str | None) -> Path:
    if not explicit:
        raise InputError("pass --runtime with the xui-lab executable path")
    return Path(explicit).expanduser().resolve()


def cmd_check(command: CheckCliCommand) -> int:
    if command.fork:
        select_fork(command)
    print(check_repository(command.viewer_source))
    return 0


def cmd_operations(command: OperationsCliCommand) -> int:
    emit_json(operations_contract(request_id=command.request_id), jq=command.jq)
    return 0


def cmd_subjects(command: SubjectsCliCommand) -> int:
    fork, source = select_fork(command)
    manifest = load_manifest()
    overrides = parse_source_overrides(command.viewer_source, manifest)
    document = subjects_contract(
        fork=fork,
        source=source,
        adapter=adapter_config(fork),
        repository_root=ROOT,
        overridden=fork.id in overrides,
        runtime=optional_runtime(command.runtime),
        fixtures=frozenset(discover_fixtures(ROOT)),
        request_id=command.request_id,
    )
    emit_json(document, jq=command.jq)
    return 0


def cmd_schema(command: SchemaCliCommand) -> int:
    catalog = SchemaCatalogContract(
        schemaVersion=SCHEMA_VERSION,
        requestId=command.request_id,
        schemas=schema_documents(),
    )
    emit_json(catalog, jq=command.jq)
    return 0


def cmd_preflight(command: PreflightCliCommand) -> int:
    fork, source = select_fork(command)
    document = preflight_contract(
        fork=fork,
        source=source,
        adapter=adapter_config(fork),
        runtime=optional_runtime(command.runtime),
        subject=command.subject,
        operation=command.operation,
        fixtures=frozenset(discover_fixtures(ROOT)),
        request_id=command.request_id,
    )
    emit_json(document, jq=command.jq)
    if command.operation is not None:
        requested = next(
            item for item in document.operations if item.name == command.operation
        )
        if not requested.available:
            return 1
    if (
        command.subject is not None
        and command.runtime is not None
        and (document.runtime is None or not document.runtime.matched)
    ):
        return 1
    if command.subject is not None and document.capabilities.missing:
        return 1
    if command.subject is not None and not document.fixture.available:
        return 1
    return 0


def scenario_paths(values: Sequence[str]) -> list[Path]:
    if values:
        return [Path(value).expanduser().resolve() for value in values]
    # Discovery also skips these. Pass a path to run one anyway.
    return sorted(
        path
        for path in (ROOT / "tests" / "scenarios").glob("*.py")
        if not path.name.startswith("_")
    )


def cmd_run(command: RunCliCommand) -> int:
    fork, source = select_fork(command)
    executable = runtime_path(fork, source, command.runtime)
    if not executable.is_file():
        raise InputError(f"runtime executable not found: {executable}")
    artifact_root = Path(command.artifacts).expanduser().resolve()
    lab = (
        None if command.dry_run else Lab(ROOT, fork, source, executable, artifact_root)
    )
    exit_status = 0
    for path in scenario_paths(command.scenarios):
        scenario = load_scenario(ROOT, path)
        if scenario.fork != fork.id:
            raise InputError(
                f"{path} targets {scenario.fork}, selected fork is {fork.id}"
            )
        if scenario.fixture is not None and not scenario.fixture.is_file():
            raise InputError(f"scenario fixture not found: {scenario.fixture}")
        artifact_dir = artifact_directory(artifact_root, scenario.id)
        if command.dry_run:
            prune = " (would prune)" if artifact_dir.exists() else ""
            print(f"{scenario.id}: would run [{artifact_dir}]{prune}")
            continue
        assert lab is not None
        try:
            with lab.open(
                artifact_id=scenario.id,
                subject=scenario.subject,
                viewport=scenario.viewport,
                capabilities=scenario.capabilities,
                fixture=scenario.fixture,
                request_id=command.request_id,
            ) as window:
                scenario.run(window)
        except Exception as error:
            message = str(error) or error.__class__.__name__
            print(f"{scenario.id}: {message} [{artifact_dir}]")
            exit_status = 1
        else:
            print(f"{scenario.id}: passed [{artifact_dir}]")
    return exit_status


def cmd_interactive(command: InteractiveCliCommand) -> int:
    fork, source = select_fork(command)
    executable = runtime_path(fork, source, command.runtime)
    if not executable.is_file():
        raise InputError(f"runtime executable not found: {executable}")
    config = adapter_config(fork)
    subjects = {
        name: frozenset(Capability(value) for value in subject.required_capabilities)
        for name, subject in config.subjects.items()
    }
    if command.subject not in subjects:
        raise InputError(f"subject is not declared by the adapter: {command.subject}")

    fixtures = discover_fixtures(ROOT)
    fixture = resolve_fixture(
        command.fixture,
        config.subjects[command.subject].default_fixture,
        fixtures,
        subject=command.subject,
    )
    artifact_id = command.artifact_id or datetime.now(timezone.utc).strftime(
        "interactive-%Y%m%d-%H%M%S"
    )
    lab = Lab(
        ROOT,
        fork,
        source,
        executable,
        Path(command.artifacts).expanduser().resolve(),
    )
    session = InteractiveSession(
        lab,
        InteractiveConfig(
            subject=command.subject,
            viewport=Viewport(command.width, command.height, command.ui_scale),
            fixture=fixture,
            artifact_id=artifact_id,
            request_id=command.request_id,
        ),
        subjects,
        fixtures,
        discover_scenarios(ROOT, str(fork.id)),
        default_fixtures={
            name: subject.default_fixture
            for name, subject in config.subjects.items()
            if subject.default_fixture is not None
        },
    )
    return serve_inspector(
        session,
        host=command.host,
        port=command.port,
        open_browser=not command.no_browser,
    )


def _add_jq(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--jq",
        metavar="EXPR",
        help="Filter JSON output with a jq expression.",
    )


def _add_dry_run(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the mutation without applying it.",
    )


def _add_selector_flags(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--control-id")
    group.add_argument("--model-id")
    group.add_argument("--path")
    group.add_argument("--role")
    group.add_argument("--label")
    group.add_argument("--placeholder")
    group.add_argument("--text")
    parser.add_argument("--name")


def _add_session_bound(parser: argparse.ArgumentParser, *, selector: bool) -> None:
    parser.add_argument("--session", required=True)
    parser.add_argument("--include-tree", action="store_true")
    parser.add_argument("--fields")
    _add_jq(parser)
    if selector:
        _add_selector_flags(parser)


def _add_oneshot_commands(commands: Any) -> None:
    tree = commands.add_parser(
        "tree", help="Return a concise production UI tree excerpt."
    )
    _add_session_bound(tree, selector=False)
    tree.add_argument("--path")
    pick = commands.add_parser("pick", help="Pick the control at a screen point.")
    _add_session_bound(pick, selector=False)
    pick.add_argument("--x", type=int, required=True)
    pick.add_argument("--y", type=int, required=True)
    get_command = commands.add_parser("get", help="Get one control by selector.")
    _add_session_bound(get_command, selector=True)
    click = commands.add_parser("click", help="Click a control.")
    _add_session_bound(click, selector=True)
    fill = commands.add_parser("fill", help="Replace text in a control.")
    _add_session_bound(fill, selector=True)
    fill.add_argument("--value", required=True)
    press = commands.add_parser("press", help="Press a key on a control.")
    _add_session_bound(press, selector=True)
    press.add_argument("--key", required=True)
    press.add_argument("--modifier", action="append", dest="modifiers", default=[])
    scroll = commands.add_parser("scroll", help="Send wheel input to a control.")
    _add_session_bound(scroll, selector=True)
    scroll.add_argument("--clicks", type=int, required=True)
    drag_by = commands.add_parser("drag-by", help="Drag a control by a delta.")
    _add_session_bound(drag_by, selector=True)
    drag_by.add_argument("--dx", type=int, required=True)
    drag_by.add_argument("--dy", type=int, required=True)
    drag_to = commands.add_parser("drag-to", help="Offer semantic drag-and-drop.")
    _add_session_bound(drag_to, selector=True)
    drag_to.add_argument("--target-control-id", required=True)
    resize_viewport = commands.add_parser("resize-viewport")
    _add_session_bound(resize_viewport, selector=False)
    resize_viewport.add_argument("--width", type=int, required=True)
    resize_viewport.add_argument("--height", type=int, required=True)
    resize_viewport.add_argument("--ui-scale", type=float)
    resize_subject = commands.add_parser("resize-subject")
    _add_session_bound(resize_subject, selector=False)
    resize_subject.add_argument("--width", type=int, required=True)
    resize_subject.add_argument("--height", type=int, required=True)
    capture = commands.add_parser("capture")
    _add_session_bound(capture, selector=False)
    capture.add_argument("--name")
    reload_command = commands.add_parser("reload")
    _add_session_bound(reload_command, selector=False)
    _add_dry_run(reload_command)
    diagnostics = commands.add_parser("diagnostics")
    _add_session_bound(diagnostics, selector=False)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="xui-lab")
    result.add_argument("--fork")
    result.add_argument(
        "--viewer-source", action="append", default=[], metavar="FORK_ID=PATH"
    )
    result.add_argument("--request-id")
    result.add_argument("--timeout", type=float)
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    operations = commands.add_parser(
        "operations", help="List supported query and input operations."
    )
    operations.add_argument("--json", action="store_true", required=True)
    _add_jq(operations)
    subjects = commands.add_parser(
        "subjects",
        help="List declared subjects and whether the runtime can open them.",
    )
    subjects.add_argument("--json", action="store_true", required=True)
    subjects.add_argument("--runtime")
    _add_jq(subjects)
    schema = commands.add_parser(
        "schema", help="Print the versioned JSON Schema catalog."
    )
    _add_jq(schema)
    preflight = commands.add_parser(
        "preflight",
        help="Report capability and operation availability for a subject.",
    )
    preflight.add_argument("--json", action="store_true", required=True)
    preflight.add_argument("--subject")
    preflight.add_argument("--operation")
    preflight.add_argument("--runtime")
    _add_jq(preflight)
    session = commands.add_parser(
        "session", help="Start, inspect, or close a lab session."
    )
    session_commands = session.add_subparsers(dest="session_command", required=True)
    start = session_commands.add_parser(
        "start", help="Start a noninteractive viewer session."
    )
    start.add_argument("subject")
    start.add_argument("--runtime")
    start.add_argument("--fixture")
    start.add_argument("--width", type=int, default=1200)
    start.add_argument("--height", type=int, default=800)
    start.add_argument("--ui-scale", type=float, default=1.0)
    start.add_argument("--artifacts", default=str(default_artifact_root()))
    _add_jq(start)
    status = session_commands.add_parser(
        "status", help="Show one session or every session."
    )
    status.add_argument("session_id", nargs="?")
    _add_jq(status)
    close = session_commands.add_parser("close", help="Close a session.")
    close.add_argument("session_id")
    _add_jq(close)
    _add_dry_run(close)
    jsonl = session_commands.add_parser(
        "jsonl", help="Send one typed command per stdin line to a session."
    )
    jsonl.add_argument("session_id")
    _add_jq(jsonl)
    serve = session_commands.add_parser("serve")
    serve.add_argument("--session-id", required=True)
    _add_oneshot_commands(commands)
    record = commands.add_parser("record", help="Save replayable session actions.")
    record.add_argument("--session", required=True)
    record.add_argument("--output", required=True)
    _add_jq(record)
    replay = commands.add_parser("replay", help="Replay a recorded command file.")
    replay.add_argument("file")
    replay.add_argument("--session", required=True)
    _add_jq(replay)
    cpp = commands.add_parser("cpp", help="Format or lint the adapter-owned C++ files.")
    cpp_commands = cpp.add_subparsers(dest="cpp_command", required=True)
    format_command = cpp_commands.add_parser(
        "format", help="Check or apply formatting."
    )
    format_command.add_argument("--check", action="store_true")
    format_command.add_argument("files", nargs="*")
    tidy_command = cpp_commands.add_parser(
        "tidy", help="Run clang-tidy with a real build database."
    )
    tidy_command.add_argument(
        "--compile-commands",
        required=True,
        metavar="PATH",
        help="Path to compile_commands.json or its directory.",
    )
    tidy_command.add_argument("files", nargs="*")
    run = commands.add_parser("run")
    run.add_argument("scenarios", nargs="*")
    run.add_argument("--runtime")
    run.add_argument("--artifacts", default=str(default_artifact_root()))
    _add_dry_run(run)
    interactive = commands.add_parser("interactive")
    interactive.add_argument("subject")
    interactive.add_argument("--runtime")
    interactive.add_argument("--fixture")
    interactive.add_argument("--width", type=int, default=1200)
    interactive.add_argument("--height", type=int, default=800)
    interactive.add_argument("--ui-scale", type=float, default=1.0)
    interactive.add_argument("--artifacts", default=str(default_artifact_root()))
    interactive.add_argument("--artifact-id")
    interactive.add_argument("--host", default="127.0.0.1")
    interactive.add_argument("--port", type=int, default=0)
    interactive.add_argument("--no-browser", action="store_true")
    return result


def parse_command(argv: list[str] | None = None) -> CliCommand:
    """Parse CLI syntax and validate it into the shared command model."""
    args = parser().parse_args(argv)
    command = {
        "schemaVersion": 1,
        **vars(args),
    }
    command["viewerSource"] = command.pop("viewer_source")
    if "cpp_command" in command:
        command["cppCommand"] = command.pop("cpp_command")
    if "compile_commands" in command:
        command["compileCommands"] = command.pop("compile_commands")
    if "ui_scale" in command:
        command["uiScale"] = command.pop("ui_scale")
    if "artifact_id" in command:
        command["artifactId"] = command.pop("artifact_id")
    if "no_browser" in command:
        command["noBrowser"] = command.pop("no_browser")
    if "session_command" in command:
        command["sessionCommand"] = command.pop("session_command")
    if "session_id" in command:
        command["sessionId"] = command.pop("session_id")
    if "include_tree" in command:
        command["includeTree"] = command.pop("include_tree")
    if "dry_run" in command:
        command["dryRun"] = command.pop("dry_run")
    if "control_id" in command:
        command["controlId"] = command.pop("control_id")
    if "model_id" in command:
        command["modelId"] = command.pop("model_id")
    if "target_control_id" in command:
        command["targetControlId"] = command.pop("target_control_id")
    request_id = command.pop("request_id", None)
    command["requestId"] = request_id or new_request_id()
    parsed = parse_cli_command(command)
    if parsed.jq is not None:
        compile_jq(parsed.jq)
    return parsed


def _unreachable(value: NoReturn) -> NoReturn:
    raise AssertionError(f"unhandled CLI command: {value!r}")


def dispatch(command: CliCommand) -> int:
    """Dispatch one validated command without depending on argparse state."""
    if isinstance(command, CheckCliCommand):
        return cmd_check(command)
    if isinstance(command, OperationsCliCommand):
        return cmd_operations(command)
    if isinstance(command, SubjectsCliCommand):
        return cmd_subjects(command)
    if isinstance(command, SchemaCliCommand):
        return cmd_schema(command)
    if isinstance(command, PreflightCliCommand):
        return cmd_preflight(command)
    if isinstance(command, SessionStartCliCommand):
        return cmd_session_start(
            command,
            select_fork=select_fork,
            runtime_path=runtime_path,
            adapter_config=adapter_config,
        )
    if isinstance(command, SessionStatusCliCommand):
        return cmd_session_status(command)
    if isinstance(command, SessionCloseCliCommand):
        return cmd_session_close(command)
    if isinstance(command, SessionJsonlCliCommand):
        return cmd_session_jsonl(command)
    if isinstance(command, SessionServeCliCommand):
        return cmd_session_serve(command)
    if isinstance(
        command,
        (
            TreeCliCommand,
            PickCliCommand,
            GetCliCommand,
            ClickCliCommand,
            FillCliCommand,
            PressCliCommand,
            ScrollCliCommand,
            DragByCliCommand,
            DragToCliCommand,
            ResizeViewportCliCommand,
            ResizeSubjectCliCommand,
            CaptureCliCommand,
            ReloadCliCommand,
            DiagnosticsCliCommand,
        ),
    ):
        return cmd_session_bound(command)
    if isinstance(command, RecordCliCommand):
        return record_session(command)
    if isinstance(command, ReplayCliCommand):
        return replay_file(command)
    if isinstance(command, RunCliCommand):
        return cmd_run(command)
    if isinstance(command, InteractiveCliCommand):
        return cmd_interactive(command)
    if isinstance(command, CppFormatCliCommand):
        return format_cpp(command)
    if isinstance(command, CppTidyCliCommand):
        return tidy_cpp(command)
    return _unreachable(command)


def main(argv: list[str] | None = None) -> int:
    try:
        command = parse_command(argv)
    except XUILabError as error:
        operation = json_operation_from_argv(argv) or "cli"
        return report_error(
            error,
            operation=operation,
            request_id=request_id_from_argv(argv),
            json_output=operation in JSON_COMMANDS,
        )
    try:
        result = dispatch(command)
        if not isinstance(result, int) or isinstance(result, bool):
            raise InputError("command handler returned an invalid exit status")
        return result
    except XUILabError as error:
        return report_error(
            error,
            operation=command.command,
            request_id=command.request_id,
            json_output=writes_json(command),
        )


if __name__ == "__main__":
    raise SystemExit(main())
