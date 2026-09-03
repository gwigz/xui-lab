"""JSON and source-resolution boundary helpers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import parse_fork_manifest
from .domain import Fork, ForkId, ForkSource, Manifest
from .errors import InputError


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise InputError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise InputError(f"invalid JSON in {path}: {error}") from error


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def parse_manifest(root: Path, raw: Any) -> Manifest:
    contract = parse_fork_manifest(raw)
    forks = {
        ForkId(entry.id): Fork(
            id=ForkId(entry.id),
            display_name=entry.display_name,
            source=ForkSource(root.joinpath(*PurePosixPath(entry.source.path).parts)),
            adapter=root.joinpath(*PurePosixPath(entry.adapter).parts),
            resource_root=PurePosixPath(entry.resource_root),
        )
        for entry in contract.forks
    }
    return Manifest(ForkId(contract.default_fork), forks)


def parse_source_overrides(values: list[str], manifest: Manifest) -> dict[ForkId, Path]:
    overrides: dict[ForkId, Path] = {}
    for value in values:
        fork_text, separator, path_text = value.partition("=")
        fork_id = ForkId(fork_text)
        if not separator or not fork_text or not path_text:
            raise InputError("--viewer-source must use FORK_ID=PATH")
        if fork_id not in manifest.forks:
            raise InputError(f"unknown fork in --viewer-source: {fork_id}")
        if fork_id in overrides:
            raise InputError(f"duplicate source override for fork: {fork_id}")
        overrides[fork_id] = Path(path_text).expanduser().resolve()
    return overrides


def resolved_source(fork: Fork, overrides: dict[ForkId, Path]) -> Path:
    source = overrides.get(fork.id, fork.source.path).resolve()
    if not source.is_dir():
        raise InputError(f"viewer source does not exist for {fork.id}: {source}")
    resource_root = source.joinpath(*fork.resource_root.parts)
    if not resource_root.is_dir():
        raise InputError(f"viewer source for {fork.id} has no {fork.resource_root}")
    return source


def git_commit(source: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise InputError(
            f"cannot resolve viewer commit for {source}: {error}"
        ) from error
    return result.stdout.strip()
