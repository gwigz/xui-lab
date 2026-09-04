"""Machine-readable discovery for commands supported by the runtime contract."""

from __future__ import annotations

from pathlib import Path

from .contracts import (
    SCHEMA_VERSION,
    AdapterContract,
    OperationArgumentContract,
    OperationContract,
    OperationsContract,
    PreflightCapabilityReport,
    PreflightContract,
    PreflightFixtureReport,
    PreflightOperationReport,
    SelectedRuntimeContract,
    SubjectContract,
    SubjectsContract,
    SubjectSourceContract,
)
from .domain import Fork
from .errors import InputError
from .io import git_commit, matching_runtime_commit, read_runtime_metadata


def _argument(
    name: str, type_: str, *, required: bool = True
) -> OperationArgumentContract:
    return OperationArgumentContract.model_validate(
        {"name": name, "type": type_, "required": required}
    )


SELECTOR = _argument("selector", "selector")
POSITION = (_argument("x", "integer"), _argument("y", "integer"))


def _operation(
    name: str,
    kind: str,
    capabilities: str | tuple[str, ...],
    *argument_sets: tuple[OperationArgumentContract, ...],
) -> OperationContract:
    required_capabilities = (
        (capabilities,) if isinstance(capabilities, str) else capabilities
    )
    return OperationContract.model_validate(
        {
            "name": name,
            "kind": kind,
            "requiredCapabilities": required_capabilities,
            "argumentSets": argument_sets or ((),),
        }
    )


def operations_contract(*, request_id: str | None = None) -> OperationsContract:
    """Return the complete public query and input operation catalog."""
    operations = (
        _operation(
            "tree",
            "query",
            "inspection",
            (_argument("path", "string", required=False),),
        ),
        _operation("menus", "query", ("inspection", "menus")),
        _operation("inventory", "query", ("inspection", "inventory_model")),
        _operation("value", "query", "inspection", (_argument("path", "string"),)),
        _operation("click", "input", "input", (SELECTOR,), POSITION),
        _operation("doubleClick", "input", "input", (SELECTOR,), POSITION),
        _operation("rightClick", "input", "input", (SELECTOR,), POSITION),
        _operation(
            "fill",
            "input",
            "input",
            (SELECTOR, _argument("text", "string")),
        ),
        _operation(
            "text",
            "input",
            "input",
            (SELECTOR, _argument("text", "string")),
        ),
        _operation(
            "key",
            "input",
            "input",
            (
                SELECTOR,
                _argument("key", "string"),
                _argument("modifiers", "string[]", required=False),
            ),
        ),
        _operation(
            "scroll",
            "input",
            "input",
            (SELECTOR, _argument("clicks", "integer")),
            (*POSITION, _argument("clicks", "integer")),
        ),
        _operation(
            "drag",
            "input",
            "input",
            (
                _argument("startX", "integer"),
                _argument("startY", "integer"),
                _argument("endX", "integer"),
                _argument("endY", "integer"),
            ),
            (
                SELECTOR,
                _argument("deltaX", "integer"),
                _argument("deltaY", "integer"),
            ),
        ),
        _operation(
            "dragAndDrop",
            "input",
            ("input", "inventory_model"),
            (_argument("source", "selector"), _argument("target", "selector")),
        ),
    )
    return OperationsContract(
        schemaVersion=SCHEMA_VERSION, requestId=request_id, operations=operations
    )


def selected_runtime_record(
    fork: Fork, source: Path, source_commit: str, runtime: Path
) -> SelectedRuntimeContract:
    """Read `--metadata` and compare it to the selected viewer source."""
    metadata = read_runtime_metadata(runtime)
    return SelectedRuntimeContract(
        path=str(runtime),
        fork=metadata.fork,
        commit=metadata.fork_commit,
        matched=matching_runtime_commit(source, fork.id, source_commit, metadata)
        is not None,
    )


def subjects_contract(
    *,
    fork: Fork,
    source: Path,
    adapter: AdapterContract,
    repository_root: Path,
    overridden: bool,
    runtime: Path | None,
    fixtures: frozenset[str],
    request_id: str | None = None,
) -> SubjectsContract:
    """List declared subjects and whether the selected runtime can open them."""
    commit = git_commit(source)
    runtime_record = None
    matched = False
    if runtime is not None:
        runtime_record = selected_runtime_record(fork, source, commit, runtime)
        matched = runtime_record.matched
    subjects = tuple(
        SubjectContract.model_validate(
            {
                "name": name,
                "requiredCapabilities": subject.required_capabilities,
                "defaultFixture": subject.default_fixture,
                "openable": runtime is not None
                and matched
                and (
                    subject.default_fixture is None
                    or subject.default_fixture in fixtures
                ),
                "unavailableReason": (
                    "runtime_not_selected"
                    if runtime is None
                    else "source_mismatch"
                    if not matched
                    else "fixture_missing"
                    if subject.default_fixture is not None
                    and subject.default_fixture not in fixtures
                    else None
                ),
            }
        )
        for name, subject in sorted(adapter.subjects.items())
    )
    return SubjectsContract(
        schemaVersion=SCHEMA_VERSION,
        requestId=request_id,
        fork=fork.id,
        source=SubjectSourceContract.model_validate(
            {
                "displayName": fork.display_name,
                "path": str(source),
                "commit": commit,
                "overridden": overridden,
                "adapter": fork.adapter.relative_to(repository_root).as_posix(),
                "resourceRoot": str(fork.resource_root),
            }
        ),
        runtime=runtime_record,
        subjects=subjects,
    )


def preflight_contract(
    *,
    fork: Fork,
    source: Path,
    adapter: AdapterContract,
    runtime: Path | None,
    subject: str | None,
    operation: str | None,
    fixtures: frozenset[str],
    request_id: str,
) -> PreflightContract:
    """Report capability and operation availability for the selected subject."""
    catalog = operations_contract(request_id=request_id)
    names = {item.name for item in catalog.operations}
    if operation is not None and operation not in names:
        raise InputError(f"unknown operation: {operation}")
    if subject is not None and subject not in adapter.subjects:
        raise InputError(f"subject is not declared by the adapter: {subject}")

    declared = adapter.capabilities
    declaration = adapter.subjects[subject] if subject is not None else None
    required = declaration.required_capabilities if declaration is not None else ()
    default_fixture = declaration.default_fixture if declaration is not None else None
    fixture_available = default_fixture is None or default_fixture in fixtures
    available_caps = frozenset(required if subject is not None else declared)
    missing = tuple(capability for capability in required if capability not in declared)
    available = tuple(
        capability for capability in (required or declared) if capability in declared
    )
    commit = git_commit(source)
    runtime_record = (
        selected_runtime_record(fork, source, commit, runtime)
        if runtime is not None
        else None
    )
    runtime_blocked = runtime_record is not None and not runtime_record.matched

    def missing_capabilities(item: OperationContract) -> tuple[str, ...]:
        return tuple(sorted(set(item.required_capabilities) - available_caps))

    available_names = tuple(
        item.name
        for item in catalog.operations
        if not runtime_blocked and fixture_available and not missing_capabilities(item)
    )
    reports = tuple(
        PreflightOperationReport.model_validate(
            {
                "name": item.name,
                "kind": item.kind,
                "available": not runtime_blocked
                and fixture_available
                and not missing_capabilities(item),
                "requiredCapabilities": item.required_capabilities,
                "missingCapabilities": missing_capabilities(item),
                "suggestedOperations": (
                    ()
                    if runtime_blocked
                    or not fixture_available
                    or not missing_capabilities(item)
                    else available_names
                ),
                "unavailableReason": (
                    "source_mismatch"
                    if runtime_blocked
                    else "fixture_missing"
                    if not fixture_available
                    else "missing_capability"
                    if missing_capabilities(item)
                    else None
                ),
            }
        )
        for item in catalog.operations
    )
    return PreflightContract(
        schemaVersion=SCHEMA_VERSION,
        requestId=request_id,
        fork=fork.id,
        subject=subject,
        runtime=runtime_record,
        capabilities=PreflightCapabilityReport(
            declared=declared,
            required=required,
            available=available,
            missing=missing,
        ),
        fixture=PreflightFixtureReport(
            defaultFixture=default_fixture,
            available=fixture_available,
            unavailableReason=None if fixture_available else "fixture_missing",
        ),
        operations=reports,
    )
