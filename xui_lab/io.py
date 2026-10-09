"""JSON and source-resolution boundary helpers."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import (
    RuntimeMetadataContract,
    parse_fork_manifest,
    parse_runtime_metadata,
)
from .domain import Fork, ForkId, ForkSource, Manifest
from .errors import InputError, RuntimeFailure


def read_json(path: Path) -> Any:
    try:
        with (
            gzip.open(path, "rt", encoding="utf-8")
            if path.suffix == ".gz"
            else path.open(encoding="utf-8")
        ) as stream:
            return json.load(stream)
    except OSError as error:
        raise InputError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise InputError(f"invalid JSON in {path}: {error}") from error


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return size, digest.hexdigest()


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


def parse_source_overrides(
    values: Sequence[str], manifest: Manifest
) -> dict[ForkId, Path]:
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


def _git_tree(source: Path, commit: str) -> str | None:
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "--verify", f"{commit}^{{tree}}"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def matching_runtime_commit(
    source: Path,
    fork_id: ForkId,
    source_commit: str,
    metadata: RuntimeMetadataContract,
) -> str | None:
    """Return the runtime commit when it represents the selected source tree."""
    if metadata.fork != fork_id:
        return None
    if metadata.fork_commit == source_commit:
        return metadata.fork_commit
    source_tree = _git_tree(source, source_commit)
    runtime_tree = _git_tree(source, metadata.fork_commit)
    if source_tree is None or source_tree != runtime_tree:
        return None
    return metadata.fork_commit


def read_runtime_metadata(
    executable: Path, *, timeout: float = 10.0
) -> RuntimeMetadataContract:
    """Read fork identity from a lab runtime without starting a viewer session."""
    try:
        completed = subprocess.run(
            [str(executable), "--metadata"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except OSError as error:
        raise RuntimeFailure(f"cannot start runtime {executable}: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeFailure(
            f"runtime metadata stalled for {timeout:g}s from {executable}"
        ) from error
    if completed.returncode != 0:
        raise RuntimeFailure(
            f"runtime metadata command failed with status {completed.returncode}: "
            f"{executable}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeFailure(
            f"invalid JSON in runtime metadata from {executable}: {error}"
        ) from error
    return parse_runtime_metadata(payload)
