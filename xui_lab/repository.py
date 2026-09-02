"""Check the xui-lab repository manifest and its declared viewer sources."""

from __future__ import annotations

import configparser
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .domain import Fork, parse_manifest
from .errors import InputError, XUILabError
from .inspector_assets import inspector_assets_problem, inspector_build_instruction
from .markdown_style import audit_markdown
from .scenarios import discover_scenarios

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SPEC_HEADINGS = (
    "## Problem statement",
    "## Solution",
    "## User stories",
    "## Implementation decisions",
    "## Testing decisions",
    "## Out of scope",
    "## Further notes",
)
REQUIRED_AGENT_TEXT = (
    "SPEC.md",
    "forks.json",
    "./xui-lab check",
    "CMAKE_CXX_STANDARD",
    "Do not push",
)


class CheckError(XUILabError):
    """The repository violates its checked contract."""


@dataclass(frozen=True)
class Adapter:
    capabilities: frozenset[str]
    subjects: dict[str, frozenset[str]]


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
        manifest = parse_manifest(REPO_ROOT, json.loads(manifest_path.read_text()))
    except (OSError, json.JSONDecodeError, InputError) as error:
        raise CheckError(f"cannot read {manifest_path.name}: {error}") from error

    schema_path = REPO_ROOT / "schemas" / "forks.schema.json"
    try:
        json.loads(schema_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise CheckError(f"cannot read the fork schema: {error}") from error
    return str(manifest.default_fork), list(manifest.forks.values())


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
        if not section.startswith('submodule "') or not parser.has_option(
            section, "path"
        ):
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
    stories = re.findall(
        r"^\d+\. As an? .+, I want .+, so that .+$", text, re.MULTILINE
    )
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


def load_adapter(fork: Fork) -> Adapter:
    path = fork.adapter / "adapter.json"
    try:
        data = require_mapping(json.loads(path.read_text()), f"adapter {fork.id}")
    except (OSError, json.JSONDecodeError) as error:
        raise CheckError(f"cannot read {path}: {error}") from error
    allowed = {
        "$schema",
        "schemaVersion",
        "fork",
        "productionTarget",
        "capabilities",
        "subjects",
    }
    reject_unknown_keys(data, allowed, f"adapter {fork.id}")
    if data.get("schemaVersion") != 1:
        raise CheckError(f"adapter {fork.id}.schemaVersion must be 1")
    if data.get("fork") != fork.id:
        raise CheckError(f"adapter {fork.id}.fork must be {fork.id}")
    require_string(data, "productionTarget", f"adapter {fork.id}")
    capabilities_value = data.get("capabilities")
    if not isinstance(capabilities_value, list) or any(
        not isinstance(value, str) or not value for value in capabilities_value
    ):
        raise CheckError(f"adapter {fork.id}.capabilities must be an array of strings")
    capabilities = frozenset(capabilities_value)
    if len(capabilities) != len(capabilities_value):
        raise CheckError(f"adapter {fork.id}.capabilities contains duplicates")
    subjects_value = require_mapping(
        data.get("subjects"), f"adapter {fork.id}.subjects"
    )
    subjects: dict[str, frozenset[str]] = {}
    for subject, required_value in subjects_value.items():
        if not isinstance(subject, str) or not subject:
            raise CheckError(f"adapter {fork.id}.subjects contains an invalid name")
        if not isinstance(required_value, list) or any(
            not isinstance(value, str) or not value for value in required_value
        ):
            raise CheckError(
                f"adapter {fork.id}.subjects.{subject} must be an array of strings"
            )
        required = frozenset(required_value)
        unknown = sorted(required - capabilities)
        if unknown:
            raise CheckError(
                f"adapter {fork.id}.subjects.{subject} uses unknown capabilities: "
                f"{', '.join(unknown)}"
            )
        subjects[subject] = required
    return Adapter(capabilities, subjects)


def check_fixture(path: Path) -> None:
    try:
        data = require_mapping(json.loads(path.read_text()), str(path))
    except (OSError, json.JSONDecodeError) as error:
        raise CheckError(f"cannot read fixture {path}: {error}") from error
    if data.get("schemaVersion") != 1:
        raise CheckError(f"{path}.schemaVersion must be 1")
    inventory = data.get("inventory")
    if not isinstance(inventory, list):
        raise CheckError(f"{path}.inventory must be an array")
    identifiers: set[str] = set()
    for index, entry_value in enumerate(inventory):
        entry = require_mapping(entry_value, f"{path}.inventory[{index}]")
        identifier = require_string(entry, "id", f"{path}.inventory[{index}]")
        if identifier in identifiers:
            raise CheckError(f"{path} contains duplicate inventory id: {identifier}")
        identifiers.add(identifier)


def check_scenarios(adapters: dict[str, Adapter]) -> None:
    legacy = sorted((REPO_ROOT / "scenarios").glob("*.json"))
    if legacy:
        raise CheckError("JSON scenarios are no longer supported")
    try:
        scenarios = discover_scenarios(REPO_ROOT)
    except InputError as error:
        raise CheckError(f"invalid Python scenario: {error}") from error
    if not scenarios:
        raise CheckError("no Python scenarios are defined")
    for scenario in scenarios.values():
        adapter = adapters.get(scenario.fork)
        if adapter is None:
            raise CheckError(
                f"scenario {scenario.id} names unknown fork: {scenario.fork}"
            )
        if scenario.subject not in adapter.subjects:
            raise CheckError(
                f"scenario {scenario.id} names unregistered subject: {scenario.subject}"
            )
        unknown = sorted(
            str(value) for value in scenario.capabilities - adapter.capabilities
        )
        if unknown:
            raise CheckError(
                f"scenario {scenario.id} requires undeclared capabilities: {', '.join(unknown)}"
            )
        subject_missing = sorted(
            adapter.subjects[scenario.subject] - scenario.capabilities
        )
        if subject_missing:
            raise CheckError(
                f"scenario {scenario.id} omits subject capabilities: {', '.join(subject_missing)}"
            )
        if scenario.fixture:
            if not scenario.fixture.is_file():
                raise CheckError(
                    f"scenario {scenario.id} fixture is missing: {scenario.fixture}"
                )
            check_fixture(scenario.fixture)


def check_fork(
    fork: Fork, source: Path, submodule_paths: set[Path], overridden: bool
) -> None:
    if not fork.adapter.is_dir():
        raise CheckError(f"adapter directory is missing for {fork.id}")
    if not (fork.adapter / "README.md").is_file():
        raise CheckError(f"adapter contract is missing for {fork.id}")
    if not source.is_dir():
        raise CheckError(
            f"viewer source is missing for {fork.id}; initialize submodules or pass "
            f"--viewer-source {fork.id}=PATH"
        )
    if not overridden:
        if fork.source.path not in submodule_paths:
            raise CheckError(
                f"viewer source is not registered as a submodule: {fork.id}"
            )
        if not (source / ".git").exists():
            raise CheckError(f"viewer submodule is not initialized: {fork.id}")
    resource_path = source.joinpath(*fork.resource_root.parts)
    if not resource_path.is_dir():
        raise CheckError(
            f"viewer source for {fork.id} does not contain {fork.resource_root}"
        )


def check_repository(viewer_sources: list[str]) -> str:
    default_fork, forks = load_manifest()
    overrides = parse_overrides(viewer_sources, {fork.id for fork in forks})
    submodule_paths = load_submodule_paths()
    check_spec()
    check_agent_guidance()
    adapters: dict[str, Adapter] = {}
    for fork in forks:
        check_fork(
            fork,
            overrides.get(fork.id, fork.source.path),
            submodule_paths,
            fork.id in overrides,
        )
        adapters[fork.id] = load_adapter(fork)
    check_scenarios(adapters)
    assets_problem = inspector_assets_problem()
    if assets_problem is not None:
        raise CheckError(f"{assets_problem}; {inspector_build_instruction()}")
    markdown_findings = audit_markdown()
    if markdown_findings:
        details = "\n".join(markdown_findings)
        raise CheckError(f"Markdown style audit failed:\n{details}")
    fork_names = ", ".join(fork.id for fork in forks)
    return (
        f"xui-lab repository is consistent; default fork: {default_fork}; "
        f"declared forks: {fork_names}"
    )
