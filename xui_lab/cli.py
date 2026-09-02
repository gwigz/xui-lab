"""Command-line entry point for xui-lab."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .domain import ForkId, parse_manifest, parse_scenario
from .errors import InputError, XUILabError
from .io import parse_source_overrides, read_json, resolved_source
from .runner import ScenarioRunner

ROOT = Path(__file__).resolve().parents[1]


def load_manifest():
    return parse_manifest(ROOT, read_json(ROOT / "forks.json"))


def select_fork(args: argparse.Namespace):
    manifest = load_manifest()
    fork_id = ForkId(args.fork or manifest.default_fork)
    try:
        fork = manifest.forks[fork_id]
    except KeyError as error:
        raise InputError(f"unknown fork: {fork_id}") from error
    overrides = parse_source_overrides(args.viewer_source, manifest)
    return fork, resolved_source(fork, overrides)


def adapter_config(fork) -> dict:
    data = read_json(fork.adapter / "adapter.json")
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise InputError(f"invalid adapter contract: {fork.adapter / 'adapter.json'}")
    return data


def runtime_path(fork, source: Path, explicit: str | None) -> Path:
    if not explicit:
        raise InputError("pass --runtime with the xui-lab executable path")
    return Path(explicit).expanduser().resolve()


def cmd_check(args: argparse.Namespace) -> int:
    fork, source = select_fork(args)
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "check.py"),
            "--viewer-source",
            f"{fork.id}={source}",
        ]
    ).returncode


def scenario_paths(values: list[str]) -> list[Path]:
    return (
        [Path(value).expanduser().resolve() for value in values]
        if values
        else sorted((ROOT / "scenarios").glob("*.json"))
    )


def cmd_run(args: argparse.Namespace) -> int:
    fork, source = select_fork(args)
    executable = runtime_path(fork, source, args.runtime)
    if not executable.is_file():
        raise InputError(f"runtime executable not found: {executable}")
    artifact_root = Path(args.artifacts).expanduser().resolve()
    exit_status = 0
    for path in scenario_paths(args.scenarios):
        scenario = parse_scenario(ROOT, read_json(path), str(path))
        if scenario.fork != fork.id:
            raise InputError(
                f"{path} targets {scenario.fork}, selected fork is {fork.id}"
            )
        result = ScenarioRunner(ROOT, fork, source, executable, artifact_root).run(
            scenario
        )
        print(f"{result.scenario_id}: {result.message} [{result.artifact_dir}]")
        if not result.passed:
            exit_status = 1
    return exit_status


def cmd_interactive(args: argparse.Namespace) -> int:
    fork, source = select_fork(args)
    executable = runtime_path(fork, source, args.runtime)
    if not executable.is_file():
        raise InputError(f"runtime executable not found: {executable}")
    return subprocess.run(
        [
            str(executable),
            "--interactive",
            "--resource-root",
            str(source.joinpath(*fork.resource_root.parts)),
            "--subject",
            args.subject,
        ]
    ).returncode


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="xui-lab")
    result.add_argument("--fork")
    result.add_argument(
        "--viewer-source", action="append", default=[], metavar="FORK_ID=PATH"
    )
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("check").set_defaults(handler=cmd_check)
    run = commands.add_parser("run")
    run.add_argument("scenarios", nargs="*")
    run.add_argument("--runtime")
    run.add_argument("--artifacts", default=str(ROOT / "artifacts"))
    run.set_defaults(handler=cmd_run)
    interactive = commands.add_parser("interactive")
    interactive.add_argument("subject")
    interactive.add_argument("--runtime")
    interactive.set_defaults(handler=cmd_interactive)
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        return args.handler(args)
    except XUILabError as error:
        print(f"xui-lab: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
