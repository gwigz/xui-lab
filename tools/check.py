#!/usr/bin/env python3
"""Check the xui-lab repository manifest and its declared viewer sources."""

from __future__ import annotations

import argparse
import configparser
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SPEC_HEADINGS = (
    "## Problem Statement",
    "## Solution",
    "## User Stories",
    "## Implementation Decisions",
    "## Testing Decisions",
    "## Out of Scope",
    "## Further Notes",
)
REQUIRED_AGENT_TEXT = (
    "SPEC.md",
    "forks.json",
    "python3 tools/check.py",
    ".gwigz/remote-build",
    "Do not push",
)
FORK_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
ROOT_KEYS = {"$schema", "schemaVersion", "defaultFork", "forks"}
FORK_KEYS = {
    "id",
    "displayName",
    "source",
    "adapter",
    "buildDriver",
    "resourceRoot",
}
SOURCE_KEYS = {"type", "path"}


class CheckError(ValueError):
    """A repository boundary input is invalid."""


@dataclass(frozen=True)
class Fork:
    id: str
    source_path: Path
    adapter_path: Path
    resource_root: PurePosixPath


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CheckError(f"{label} must be an object")
    return value


def require_string(mapping: dict[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise CheckError(f"{label}.{key} must be a non-empty string")
    return value


def relative_path(value: str, label: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise CheckError(f"{label} must be a repository-relative path")
    return REPO_ROOT.joinpath(*path.parts)


def reject_unknown_keys(mapping: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise CheckError(f"{label} contains unknown keys: {', '.join(unknown)}")


def load_manifest() -> tuple[str, list[Fork]]:
    manifest_path = REPO_ROOT / "forks.json"
    try:
        manifest = require_mapping(json.loads(manifest_path.read_text()), "manifest")
    except (OSError, json.JSONDecodeError) as error:
        raise CheckError(f"cannot read {manifest_path.name}: {error}") from error

    reject_unknown_keys(manifest, ROOT_KEYS, "manifest")
    schema_path = require_string(manifest, "$schema", "manifest")
    if schema_path != "schemas/forks.schema.json":
        raise CheckError("manifest.$schema must name schemas/forks.schema.json")
    try:
        json.loads((REPO_ROOT / schema_path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise CheckError(f"cannot read the fork schema: {error}") from error

    if manifest.get("schemaVersion") != 1:
        raise CheckError("manifest.schemaVersion must be 1")

    default_fork = require_string(manifest, "defaultFork", "manifest")
    entries = manifest.get("forks")
    if not isinstance(entries, list) or not entries:
        raise CheckError("manifest.forks must be a non-empty array")

    forks: list[Fork] = []
    seen: set[str] = set()
    for index, raw_entry in enumerate(entries):
        label = f"manifest.forks[{index}]"
        entry = require_mapping(raw_entry, label)
        reject_unknown_keys(entry, FORK_KEYS, label)
        fork_id = require_string(entry, "id", label)
        if not FORK_ID_PATTERN.fullmatch(fork_id):
            raise CheckError(f"{label}.id has an invalid format")
        if fork_id in seen:
            raise CheckError(f"duplicate fork id: {fork_id}")
        seen.add(fork_id)

        require_string(entry, "displayName", label)
        require_string(entry, "buildDriver", label)
        source = require_mapping(entry.get("source"), f"{label}.source")
        reject_unknown_keys(source, SOURCE_KEYS, f"{label}.source")
        if source.get("type") != "submodule":
            raise CheckError(f"{label}.source.type must be 'submodule'")
        source_path = relative_path(
            require_string(source, "path", f"{label}.source"),
            f"{label}.source.path",
        )
        adapter_path = relative_path(
            require_string(entry, "adapter", label), f"{label}.adapter"
        )
        resource_root = PurePosixPath(require_string(entry, "resourceRoot", label))
        if resource_root.is_absolute() or ".." in resource_root.parts:
            raise CheckError(f"{label}.resourceRoot must be a relative path")

        forks.append(Fork(fork_id, source_path, adapter_path, resource_root))

    if default_fork not in seen:
        raise CheckError("manifest.defaultFork does not name a declared fork")
    return default_fork, forks


def parse_overrides(values: list[str], known_ids: set[str]) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for value in values:
        fork_id, separator, raw_path = value.partition("=")
        if not separator or not fork_id or not raw_path:
            raise CheckError("--viewer-source must use FORK_ID=PATH")
        if fork_id not in known_ids:
            raise CheckError(f"unknown fork in --viewer-source: {fork_id}")
        if fork_id in overrides:
            raise CheckError(f"duplicate source override for fork: {fork_id}")
        overrides[fork_id] = Path(raw_path).expanduser().resolve()
    return overrides


def load_submodule_paths() -> set[Path]:
    modules_path = REPO_ROOT / ".gitmodules"
    parser = configparser.RawConfigParser()
    try:
        with modules_path.open() as modules_file:
            parser.read_file(modules_file)
    except (OSError, configparser.Error) as error:
        raise CheckError(f"cannot read .gitmodules: {error}") from error

    paths: set[Path] = set()
    for section in parser.sections():
        if not section.startswith('submodule "') or not parser.has_option(section, "path"):
            continue
        paths.add(relative_path(parser.get(section, "path"), f"{section}.path"))
    return paths


def check_spec() -> None:
    spec_path = REPO_ROOT / "SPEC.md"
    try:
        text = spec_path.read_text()
    except OSError as error:
        raise CheckError(f"cannot read {spec_path.name}: {error}") from error
    missing = [heading for heading in REQUIRED_SPEC_HEADINGS if heading not in text]
    if missing:
        raise CheckError(f"SPEC.md is missing headings: {', '.join(missing)}")
    stories = re.findall(r"^\d+\. As an? .+, I want .+, so that .+$", text, re.MULTILINE)
    if len(stories) < 20:
        raise CheckError("SPEC.md must contain at least 20 formatted user stories")


def check_agent_guidance() -> None:
    guidance_path = REPO_ROOT / "AGENTS.md"
    try:
        text = guidance_path.read_text()
    except OSError as error:
        raise CheckError(f"cannot read {guidance_path.name}: {error}") from error
    missing = [value for value in REQUIRED_AGENT_TEXT if value not in text]
    if missing:
        raise CheckError(
            f"AGENTS.md is missing required guidance: {', '.join(missing)}"
        )


def check_fork(fork: Fork, source: Path, submodule_paths: set[Path], overridden: bool) -> None:
    if not fork.adapter_path.is_dir():
        raise CheckError(f"adapter directory is missing for {fork.id}")
    if not (fork.adapter_path / "README.md").is_file():
        raise CheckError(f"adapter contract is missing for {fork.id}")
    if not source.is_dir():
        raise CheckError(
            f"viewer source is missing for {fork.id}; initialize submodules or pass "
            f"--viewer-source {fork.id}=PATH"
        )
    if not overridden:
        if fork.source_path not in submodule_paths:
            raise CheckError(f"viewer source is not registered as a submodule: {fork.id}")
        if not (source / ".git").exists():
            raise CheckError(f"viewer submodule is not initialized: {fork.id}")
    resource_path = source.joinpath(*fork.resource_root.parts)
    if not resource_path.is_dir():
        raise CheckError(
            f"viewer source for {fork.id} does not contain {fork.resource_root}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--viewer-source",
        action="append",
        default=[],
        metavar="FORK_ID=PATH",
        help="use a local viewer checkout instead of its pinned submodule",
    )
    args = parser.parse_args()

    try:
        default_fork, forks = load_manifest()
        overrides = parse_overrides(args.viewer_source, {fork.id for fork in forks})
        submodule_paths = load_submodule_paths()
        check_spec()
        check_agent_guidance()
        for fork in forks:
            check_fork(
                fork,
                overrides.get(fork.id, fork.source_path),
                submodule_paths,
                fork.id in overrides,
            )
    except CheckError as error:
        print(f"xui-lab check failed: {error}", file=sys.stderr)
        return 1

    fork_names = ", ".join(fork.id for fork in forks)
    print(
        f"xui-lab repository is consistent; default fork: {default_fork}; "
        f"declared forks: {fork_names}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
