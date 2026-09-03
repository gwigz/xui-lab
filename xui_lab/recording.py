"""Selector-stable CLI recordings."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, TypeAdapter, ValidationError

from .contracts import (
    SCHEMA_VERSION,
    ContractModel,
    DiagnosticsCliCommand,
    FrozenTuple,
    NonEmptyString,
    PositiveFloat,
    PositiveInt,
    RecordCliCommand,
    ReplayCliCommand,
    Selector,
    TreeCliCommand,
    VersionedContract,
    parse_cli_command,
)
from .errors import ContractViolation, InputError
from .io import read_json, write_json
from .json_output import emit_json_document
from .selectors import rank_locator, tree_nodes
from .session import send_session_command


class RecordedSelectorCommand(ContractModel):
    selector: Selector


class RecordedClick(RecordedSelectorCommand):
    command: Literal["click"]


class RecordedFill(RecordedSelectorCommand):
    command: Literal["fill"]
    value: str


class RecordedPress(RecordedSelectorCommand):
    command: Literal["press"]
    key: NonEmptyString
    modifiers: FrozenTuple[Literal["shift", "control", "alt"]] = ()


class RecordedScroll(RecordedSelectorCommand):
    command: Literal["scroll"]
    clicks: int = Field(strict=True)


class RecordedDragBy(RecordedSelectorCommand):
    command: Literal["drag-by"]
    dx: int = Field(strict=True)
    dy: int = Field(strict=True)


class RecordedResizeViewport(ContractModel):
    command: Literal["resize-viewport"]
    width: PositiveInt
    height: PositiveInt
    ui_scale: PositiveFloat | None = Field(default=None, alias="uiScale")


class RecordedResizeSubject(ContractModel):
    command: Literal["resize-subject"]
    width: PositiveInt
    height: PositiveInt


class RecordedCapture(ContractModel):
    command: Literal["capture"]
    name: NonEmptyString | None = None


class RecordedReload(ContractModel):
    command: Literal["reload"]


RecordedCommand: TypeAlias = Annotated[
    RecordedClick
    | RecordedFill
    | RecordedPress
    | RecordedScroll
    | RecordedDragBy
    | RecordedResizeViewport
    | RecordedResizeSubject
    | RecordedCapture
    | RecordedReload,
    Field(discriminator="command"),
]


class RecordingContract(VersionedContract):
    type: Literal["recording"]
    commands: FrozenTuple[RecordedCommand]


RecordingAdapter: TypeAdapter[RecordingContract] = TypeAdapter(RecordingContract)


def parse_recording(value: Any) -> RecordingContract:
    try:
        return RecordingAdapter.validate_python(value)
    except ValidationError as error:
        raise ContractViolation("recording") from error


def _selector_for(control_id: Any, tree: dict[str, Any]) -> Selector:
    if not isinstance(control_id, str) or not control_id:
        raise InputError("recorded action has no control id")
    matches = [
        node for node in tree_nodes(tree) if node.get("control_id") == control_id
    ]
    if len(matches) != 1:
        raise InputError(
            f"recorded control id matched {len(matches)} controls: {control_id}"
        )
    return rank_locator(matches[0], tree).selector


def recording_from_runtime(
    actions: list[dict[str, Any]], tree: dict[str, Any]
) -> RecordingContract:
    commands: list[RecordedCommand] = []
    for action in actions:
        kind = action.get("action")
        selector = _selector_for(action.get("controlId"), tree)
        if kind == "click":
            commands.append(RecordedClick(command="click", selector=selector))
        elif kind in {"fill", "text"} and isinstance(action.get("text"), str):
            commands.append(
                RecordedFill(command="fill", selector=selector, value=action["text"])
            )
        elif kind == "key" and isinstance(action.get("key"), str):
            commands.append(
                RecordedPress(
                    command="press",
                    selector=selector,
                    key=action["key"],
                    modifiers=tuple(action.get("modifiers", ())),
                )
            )
        elif kind == "scroll" and isinstance(action.get("clicks"), int):
            commands.append(
                RecordedScroll(
                    command="scroll", selector=selector, clicks=action["clicks"]
                )
            )
        elif (
            kind == "drag"
            and isinstance(action.get("deltaX"), int)
            and isinstance(action.get("deltaY"), int)
        ):
            commands.append(
                RecordedDragBy(
                    command="drag-by",
                    selector=selector,
                    dx=action["deltaX"],
                    dy=action["deltaY"],
                )
            )
        else:
            raise InputError(f"recorded action is not replayable: {kind!r}")
    return RecordingContract(
        schemaVersion=SCHEMA_VERSION, type="recording", commands=tuple(commands)
    )


def _wire(command: ContractModel) -> dict[str, Any]:
    return command.model_dump(mode="json", by_alias=True, exclude={"jq"})


def record_session(command: RecordCliCommand) -> int:
    timeout = float(command.timeout) if command.timeout is not None else 10.0
    diagnostics_command = DiagnosticsCliCommand(
        schemaVersion=SCHEMA_VERSION,
        command="diagnostics",
        fork=command.fork,
        viewerSource=command.viewer_source,
        requestId=command.request_id,
        timeout=command.timeout,
        session=command.session,
        includeTree=True,
        fields=None,
        jq=None,
    )
    tree_command = TreeCliCommand(
        schemaVersion=SCHEMA_VERSION,
        command="tree",
        fork=command.fork,
        viewerSource=command.viewer_source,
        requestId=command.request_id,
        timeout=command.timeout,
        session=command.session,
        includeTree=True,
        fields=None,
        jq=None,
        path=None,
    )
    diagnostics = send_session_command(
        command.session,
        _wire(diagnostics_command),
        timeout=timeout,
    )
    tree_result = send_session_command(
        command.session,
        _wire(tree_command),
        timeout=timeout,
    )
    diagnostics_data = diagnostics.get("data")
    tree_data = tree_result.get("data")
    actions = (
        diagnostics_data.get("recording")
        if isinstance(diagnostics_data, dict)
        else None
    )
    tree = tree_data.get("tree") if isinstance(tree_data, dict) else None
    if not isinstance(actions, list) or not all(
        isinstance(item, dict) for item in actions
    ):
        raise InputError("session diagnostics contain no valid recording")
    if not isinstance(tree, dict):
        raise InputError("session returned no production UI tree")
    recording = recording_from_runtime(actions, tree)
    output = Path(command.output).expanduser().resolve()
    write_json(output, recording.model_dump(mode="json", by_alias=True))
    emit_json_document(
        {
            "schemaVersion": SCHEMA_VERSION,
            "requestId": command.request_id,
            "operation": "record",
            "output": str(output.resolve()),
            "commandCount": len(recording.commands),
        },
        command.jq,
    )
    return 0


def _cli_payload(
    recorded: RecordedCommand, command: ReplayCliCommand, sequence: int
) -> dict[str, Any]:
    data = recorded.model_dump(mode="json", by_alias=True, exclude_none=True)
    selector = data.pop("selector", None)
    if isinstance(selector, dict):
        selector.pop("schemaVersion", None)
        selector.pop("kind", None)
        data.update(selector)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "fork": command.fork,
        "viewerSource": list(command.viewer_source),
        "requestId": f"{command.request_id}_{sequence}",
        "timeout": command.timeout,
        "session": command.session,
        "includeTree": False,
        "fields": None,
        "jq": None,
        **data,
    }


def replay_file(command: ReplayCliCommand) -> int:
    recording = parse_recording(read_json(Path(command.file)))
    timeout = float(command.timeout) if command.timeout is not None else 10.0
    results: list[dict[str, Any]] = []
    for sequence, recorded in enumerate(recording.commands, start=1):
        inner = parse_cli_command(_cli_payload(recorded, command, sequence))
        response = send_session_command(command.session, _wire(inner), timeout=timeout)
        results.append(response)
        if response.get("type") == "error":
            emit_json_document(response, command.jq)
            return 1
    emit_json_document(
        {
            "schemaVersion": SCHEMA_VERSION,
            "requestId": command.request_id,
            "operation": "replay",
            "commandCount": len(results),
            "results": results,
        },
        command.jq,
    )
    return 0
