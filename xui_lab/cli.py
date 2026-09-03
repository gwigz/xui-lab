"""Command-line entry point for xui-lab."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .api import Lab, artifact_directory
from .contracts import AdapterContract, parse_adapter, parse_cli_command
from .cpp_quality import format_cpp, tidy_cpp
from .domain import Capability, Fork, ForkId, Manifest, Viewport
from .errors import InputError, XUILabError
from .interactive import (
    InteractiveConfig,
    InteractiveSession,
    discover_fixtures,
    serve_inspector,
)
from .io import parse_manifest, parse_source_overrides, read_json, resolved_source
from .repository import check_repository
from .scenarios import discover_scenarios, load_scenario

ROOT = Path(__file__).resolve().parents[1]


def load_manifest() -> Manifest:
    return parse_manifest(ROOT, read_json(ROOT / "forks.json"))


def select_fork(args: argparse.Namespace) -> tuple[Fork, Path]:
    manifest = load_manifest()
    fork_id = ForkId(args.fork or manifest.default_fork)
    try:
        fork = manifest.forks[fork_id]
    except KeyError as error:
        raise InputError(f"unknown fork: {fork_id}") from error
    overrides = parse_source_overrides(args.viewer_source, manifest)
    return fork, resolved_source(fork, overrides)


def adapter_config(fork: Fork) -> AdapterContract:
    return parse_adapter(read_json(fork.adapter / "adapter.json"))


def runtime_path(_fork: Fork, _source: Path, explicit: str | None) -> Path:
    if not explicit:
        raise InputError("pass --runtime with the xui-lab executable path")
    return Path(explicit).expanduser().resolve()


def cmd_check(args: argparse.Namespace) -> int:
    if args.fork:
        select_fork(args)
    print(check_repository(args.viewer_source))
    return 0


def scenario_paths(values: list[str]) -> list[Path]:
    return (
        [Path(value).expanduser().resolve() for value in values]
        if values
        else sorted((ROOT / "tests" / "scenarios").glob("*.py"))
    )


def cmd_run(args: argparse.Namespace) -> int:
    fork, source = select_fork(args)
    executable = runtime_path(fork, source, args.runtime)
    if not executable.is_file():
        raise InputError(f"runtime executable not found: {executable}")
    artifact_root = Path(args.artifacts).expanduser().resolve()
    lab = Lab(ROOT, fork, source, executable, artifact_root)
    exit_status = 0
    for path in scenario_paths(args.scenarios):
        scenario = load_scenario(ROOT, path)
        if scenario.fork != fork.id:
            raise InputError(
                f"{path} targets {scenario.fork}, selected fork is {fork.id}"
            )
        if scenario.fixture is not None and not scenario.fixture.is_file():
            raise InputError(f"scenario fixture not found: {scenario.fixture}")
        artifact_dir = artifact_directory(artifact_root, scenario.id)
        try:
            with lab.open(
                artifact_id=scenario.id,
                subject=scenario.subject,
                viewport=scenario.viewport,
                capabilities=scenario.capabilities,
                fixture=scenario.fixture,
            ) as window:
                scenario.run(window)
        except Exception as error:
            message = str(error) or error.__class__.__name__
            print(f"{scenario.id}: {message} [{artifact_dir}]")
            exit_status = 1
        else:
            print(f"{scenario.id}: passed [{artifact_dir}]")
    return exit_status


def cmd_interactive(args: argparse.Namespace) -> int:
    fork, source = select_fork(args)
    executable = runtime_path(fork, source, args.runtime)
    if not executable.is_file():
        raise InputError(f"runtime executable not found: {executable}")
    config = adapter_config(fork)
    subjects = {
        name: frozenset(Capability(value) for value in capabilities)
        for name, capabilities in config.subjects.items()
    }
    if args.subject not in subjects:
        raise InputError(f"subject is not declared by the adapter: {args.subject}")

    fixture = Path(args.fixture).expanduser().resolve() if args.fixture else None
    if fixture is not None and not fixture.is_file():
        raise InputError(f"fixture not found: {fixture}")
    artifact_id = args.artifact_id or datetime.now(timezone.utc).strftime(
        "interactive-%Y%m%d-%H%M%S"
    )
    lab = Lab(
        ROOT,
        fork,
        source,
        executable,
        Path(args.artifacts).expanduser().resolve(),
    )
    session = InteractiveSession(
        lab,
        InteractiveConfig(
            subject=args.subject,
            viewport=Viewport(args.width, args.height, args.ui_scale),
            fixture=fixture,
            artifact_id=artifact_id,
        ),
        subjects,
        discover_fixtures(ROOT),
        discover_scenarios(ROOT, str(fork.id)),
    )
    return serve_inspector(
        session,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="xui-lab")
    result.add_argument("--fork")
    result.add_argument(
        "--viewer-source", action="append", default=[], metavar="FORK_ID=PATH"
    )
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("check").set_defaults(handler=cmd_check)
    cpp = commands.add_parser("cpp", help="Format or lint the adapter-owned C++ files.")
    cpp_commands = cpp.add_subparsers(dest="cpp_command", required=True)
    format_command = cpp_commands.add_parser(
        "format", help="Check or apply formatting."
    )
    format_command.add_argument("--check", action="store_true")
    format_command.add_argument("files", nargs="*")
    format_command.set_defaults(handler=format_cpp)
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
    tidy_command.set_defaults(handler=tidy_cpp)
    run = commands.add_parser("run")
    run.add_argument("scenarios", nargs="*")
    run.add_argument("--runtime")
    run.add_argument("--artifacts", default=str(ROOT / "artifacts"))
    run.set_defaults(handler=cmd_run)
    interactive = commands.add_parser("interactive")
    interactive.add_argument("subject")
    interactive.add_argument("--runtime")
    interactive.add_argument("--fixture")
    interactive.add_argument("--width", type=int, default=1200)
    interactive.add_argument("--height", type=int, default=800)
    interactive.add_argument("--ui-scale", type=float, default=1.0)
    interactive.add_argument("--artifacts", default=str(ROOT / "artifacts"))
    interactive.add_argument("--artifact-id")
    interactive.add_argument("--host", default="127.0.0.1")
    interactive.add_argument("--port", type=int, default=0)
    interactive.add_argument("--no-browser", action="store_true")
    interactive.set_defaults(handler=cmd_interactive)
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        command = {
            "schemaVersion": 1,
            **{key: value for key, value in vars(args).items() if key != "handler"},
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
        validated = parse_cli_command(command)
        domain_args = argparse.Namespace(
            **validated.model_dump(exclude={"schema_version"})
        )
        result = args.handler(domain_args)
        if not isinstance(result, int) or isinstance(result, bool):
            raise InputError("command handler returned an invalid exit status")
        return result
    except XUILabError as error:
        print(f"xui-lab: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
