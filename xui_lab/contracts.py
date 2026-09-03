"""Pydantic models for data that crosses XUI Lab process boundaries."""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal, TypeAlias, TypeVar

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from .errors import (
    AssertionFailure,
    CapabilityError,
    ContractViolation,
    InputError,
    RuntimeFailure,
)

SCHEMA_VERSION: Final[Literal[1]] = 1
ID_PATTERN = r"^[a-z][a-z0-9_-]*$"
UUID_PATTERN = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

Identifier = Annotated[str, StringConstraints(min_length=1, pattern=ID_PATTERN)]
NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
UuidString = Annotated[str, StringConstraints(pattern=UUID_PATTERN)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveFloat = Annotated[float, Field(strict=True, gt=0)]
Item = TypeVar("Item")


def _freeze_sequence(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else value


FrozenTuple: TypeAlias = Annotated[tuple[Item, ...], BeforeValidator(_freeze_sequence)]


class ContractModel(BaseModel):
    """Shared closed-world configuration for external contracts."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, populate_by_name=True, strict=True
    )


class VersionedContract(ContractModel):
    schema_version: Literal[1] = Field(alias="schemaVersion")


def _relative_path(value: str) -> str:
    parts = value.split("/")
    if not value or value.startswith("/") or ".." in parts:
        raise ValueError("path must be repository-relative")
    return value


class ForkSourceContract(ContractModel):
    type: Literal["submodule"]
    path: NonEmptyString

    _validate_path = field_validator("path")(_relative_path)


class ForkContract(ContractModel):
    id: Identifier
    display_name: NonEmptyString = Field(alias="displayName")
    source: ForkSourceContract
    adapter: NonEmptyString
    resource_root: NonEmptyString = Field(alias="resourceRoot")

    _validate_adapter = field_validator("adapter")(_relative_path)
    _validate_resource_root = field_validator("resource_root")(_relative_path)


class ForkManifestContract(VersionedContract):
    schema_ref: str | None = Field(default=None, alias="$schema")
    default_fork: Identifier = Field(alias="defaultFork")
    forks: FrozenTuple[ForkContract] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_forks(self) -> ForkManifestContract:
        ids = [fork.id for fork in self.forks]
        if len(ids) != len(set(ids)):
            raise ValueError("fork ids must be unique")
        if self.default_fork not in ids:
            raise ValueError("default fork must name a declared fork")
        return self


class AdapterContract(VersionedContract):
    schema_ref: str | None = Field(default=None, alias="$schema")
    fork: Identifier
    production_target: NonEmptyString = Field(alias="productionTarget")
    capabilities: FrozenTuple[NonEmptyString]
    subjects: dict[NonEmptyString, FrozenTuple[NonEmptyString]]

    @model_validator(mode="after")
    def validate_capabilities(self) -> AdapterContract:
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("capabilities must be unique")
        declared = set(self.capabilities)
        for required in self.subjects.values():
            if len(required) != len(set(required)):
                raise ValueError("subject capabilities must be unique")
            if not set(required) <= declared:
                raise ValueError("subjects must use declared capabilities")
        return self


class AgentFixtureContract(ContractModel):
    id: UuidString
    name: NonEmptyString


class InventoryEntryContract(ContractModel):
    id: UuidString
    parent_id: UuidString = Field(alias="parentId")
    kind: Literal["root", "folder", "notecard"]
    name: NonEmptyString


class AvatarNameFixtureContract(ContractModel):
    id: UuidString
    display_name: NonEmptyString = Field(alias="displayName")
    user_name: NonEmptyString = Field(alias="userName")


class FixtureContract(VersionedContract):
    schema_ref: str | None = Field(default=None, alias="$schema")
    id: Identifier
    agent: AgentFixtureContract
    inventory: FrozenTuple[InventoryEntryContract] = Field(min_length=1)
    avatar_names: FrozenTuple[AvatarNameFixtureContract] = Field(alias="avatarNames")

    @model_validator(mode="after")
    def validate_inventory(self) -> FixtureContract:
        ids = [entry.id.lower() for entry in self.inventory]
        if len(ids) != len(set(ids)):
            raise ValueError("inventory ids must be unique")
        roots = [entry for entry in self.inventory if entry.kind == "root"]
        if len(roots) != 1 or int(roots[0].parent_id.replace("-", ""), 16) != 0:
            raise ValueError("inventory must contain one root with a null parent")
        folders = {
            entry.id.lower() for entry in self.inventory if entry.kind != "notecard"
        }
        for entry in self.inventory:
            if entry.kind != "root" and entry.parent_id.lower() not in folders:
                raise ValueError("inventory parents must name fixture folders")
        return self


class PathSelectorContract(VersionedContract):
    kind: Literal["path"]
    path: Annotated[str, StringConstraints(min_length=1, pattern=r"^/")]

    def target(self) -> dict[str, Any]:
        return {"path": self.path}

    def describe(self) -> str:
        return f"path {self.path!r}"


class ModelIdSelectorContract(VersionedContract):
    kind: Literal["modelId"]
    model_id: UuidString = Field(alias="modelId")

    def target(self) -> dict[str, Any]:
        return {"modelId": self.model_id}

    def describe(self) -> str:
        return f"model id {self.model_id!r}"


class ControlIdSelectorContract(VersionedContract):
    kind: Literal["controlId"]
    control_id: NonEmptyString = Field(alias="controlId")

    def target(self) -> dict[str, Any]:
        return {"controlId": self.control_id}

    def describe(self) -> str:
        return f"control id {self.control_id!r}"


class RoleSelectorContract(VersionedContract):
    kind: Literal["role"]
    role: NonEmptyString
    name: NonEmptyString | None = None

    def target(self) -> dict[str, Any]:
        result = {"role": self.role}
        if self.name is not None:
            result["name"] = self.name
        return result

    def describe(self) -> str:
        if self.name is None:
            return f"role {self.role!r}"
        return f"role {self.role!r} name {self.name!r}"


class LabelSelectorContract(VersionedContract):
    kind: Literal["label"]
    label: NonEmptyString

    def target(self) -> dict[str, Any]:
        return {"label": self.label}

    def describe(self) -> str:
        return f"label {self.label!r}"


class PlaceholderSelectorContract(VersionedContract):
    kind: Literal["placeholder"]
    placeholder: NonEmptyString

    def target(self) -> dict[str, Any]:
        return {"placeholder": self.placeholder}

    def describe(self) -> str:
        return f"placeholder {self.placeholder!r}"


class TextSelectorContract(VersionedContract):
    kind: Literal["text"]
    text: NonEmptyString

    def target(self) -> dict[str, Any]:
        return {"text": self.text}

    def describe(self) -> str:
        return f"text {self.text!r}"


Selector: TypeAlias = Annotated[
    PathSelectorContract
    | ModelIdSelectorContract
    | ControlIdSelectorContract
    | RoleSelectorContract
    | LabelSelectorContract
    | PlaceholderSelectorContract
    | TextSelectorContract,
    Field(discriminator="kind"),
]
SelectorContract: TypeAdapter[Selector] = TypeAdapter(Selector)


class WirePathSelector(ContractModel):
    path: Annotated[str, StringConstraints(min_length=1, pattern=r"^/")]


class WireModelIdSelector(ContractModel):
    model_id: UuidString = Field(alias="modelId")


class WireControlIdSelector(ContractModel):
    control_id: NonEmptyString = Field(alias="controlId")


WireSelector: TypeAlias = WirePathSelector | WireModelIdSelector | WireControlIdSelector


class ViewportContract(ContractModel):
    width: PositiveInt
    height: PositiveInt
    ui_scale: PositiveFloat = Field(alias="uiScale")


class RuntimeCommandBase(VersionedContract):
    pass


class InitializeCommand(RuntimeCommandBase):
    op: Literal["initialize"]
    fork: Identifier
    fork_commit: NonEmptyString = Field(alias="forkCommit")
    resource_root: NonEmptyString = Field(alias="resourceRoot")
    subject: NonEmptyString
    viewport: ViewportContract
    fixture: FixtureContract | None
    artifact_dir: NonEmptyString = Field(alias="artifactDir")


class InstallCapabilitiesCommand(RuntimeCommandBase):
    op: Literal["installCapabilities"]
    capabilities: FrozenTuple[NonEmptyString]


class FramesCommand(RuntimeCommandBase):
    op: Literal["frames"]
    count: NonNegativeInt


class StableCommand(RuntimeCommandBase):
    op: Literal["stable"]
    consecutive_frames: PositiveInt = Field(alias="consecutiveFrames")
    maximum_frames: PositiveInt = Field(alias="maximumFrames")

    @model_validator(mode="after")
    def validate_frame_range(self) -> StableCommand:
        if self.maximum_frames < self.consecutive_frames:
            raise ValueError("maximum frames must cover consecutive frames")
        return self


class ResizeViewportCommand(RuntimeCommandBase):
    op: Literal["resizeViewport"]
    width: PositiveInt
    height: PositiveInt
    ui_scale: PositiveFloat | None = Field(default=None, alias="uiScale")


class ResizeSubjectCommand(RuntimeCommandBase):
    op: Literal["resizeSubject"]
    width: PositiveInt
    height: PositiveInt


class ReloadCommand(RuntimeCommandBase):
    op: Literal["reload"]


class TreeQueryCommand(RuntimeCommandBase):
    op: Literal["query"]
    kind: Literal["tree"]
    path: Annotated[str, StringConstraints(min_length=1, pattern=r"^/")] | None = None


class MenusQueryCommand(RuntimeCommandBase):
    op: Literal["query"]
    kind: Literal["menus"]


class InventoryQueryCommand(RuntimeCommandBase):
    op: Literal["query"]
    kind: Literal["inventory"]


class ValueQueryCommand(RuntimeCommandBase):
    op: Literal["query"]
    kind: Literal["value"]
    path: Annotated[str, StringConstraints(min_length=1, pattern=r"^/")]


QueryCommand: TypeAlias = Annotated[
    TreeQueryCommand | MenusQueryCommand | InventoryQueryCommand | ValueQueryCommand,
    Field(discriminator="kind"),
]


class TargetedInputCommand(RuntimeCommandBase):
    path: Annotated[str, StringConstraints(min_length=1, pattern=r"^/")] | None = None
    model_id: UuidString | None = Field(default=None, alias="modelId")
    control_id: NonEmptyString | None = Field(default=None, alias="controlId")

    @model_validator(mode="after")
    def validate_one_target(self) -> TargetedInputCommand:
        if (
            sum(
                value is not None
                for value in (self.path, self.model_id, self.control_id)
            )
            != 1
        ):
            raise ValueError("input command must contain exactly one selector")
        return self


class PositionedInputCommand(RuntimeCommandBase):
    path: Annotated[str, StringConstraints(min_length=1, pattern=r"^/")] | None = None
    model_id: UuidString | None = Field(default=None, alias="modelId")
    control_id: NonEmptyString | None = Field(default=None, alias="controlId")
    x: int | None = Field(default=None, strict=True)
    y: int | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def validate_position(self) -> PositionedInputCommand:
        target_count = sum(
            value is not None for value in (self.path, self.model_id, self.control_id)
        )
        coordinate_count = sum(value is not None for value in (self.x, self.y))
        if (target_count, coordinate_count) not in {(1, 0), (0, 2)}:
            raise ValueError("pointer input requires one selector or two coordinates")
        return self


class PointerInputCommand(PositionedInputCommand):
    op: Literal["input"]
    event: Literal["click", "doubleClick"]
    button: Literal["left", "right"]


class ScrollInputCommand(PositionedInputCommand):
    op: Literal["input"]
    event: Literal["scroll"]
    clicks: int = Field(strict=True)

    @model_validator(mode="after")
    def validate_clicks(self) -> ScrollInputCommand:
        if self.clicks == 0:
            raise ValueError("scroll clicks must be non-zero")
        return self


class DragInputCommand(RuntimeCommandBase):
    op: Literal["input"]
    event: Literal["drag"]
    start_x: int | None = Field(default=None, alias="startX", strict=True)
    start_y: int | None = Field(default=None, alias="startY", strict=True)
    end_x: int | None = Field(default=None, alias="endX", strict=True)
    end_y: int | None = Field(default=None, alias="endY", strict=True)
    path: Annotated[str, StringConstraints(min_length=1, pattern=r"^/")] | None = None
    model_id: UuidString | None = Field(default=None, alias="modelId")
    control_id: NonEmptyString | None = Field(default=None, alias="controlId")
    delta_x: int | None = Field(default=None, alias="deltaX", strict=True)
    delta_y: int | None = Field(default=None, alias="deltaY", strict=True)

    @model_validator(mode="after")
    def validate_drag_shape(self) -> DragInputCommand:
        coordinates = (self.start_x, self.start_y, self.end_x, self.end_y)
        targets = (self.path, self.model_id, self.control_id)
        deltas = (self.delta_x, self.delta_y)
        coordinate_drag = all(value is not None for value in coordinates) and all(
            value is None for value in (*targets, *deltas)
        )
        targeted_drag = (
            sum(value is not None for value in targets) == 1
            and all(value is not None for value in deltas)
            and all(value is None for value in coordinates)
        )
        if not coordinate_drag and not targeted_drag:
            raise ValueError("drag input has an invalid shape")
        return self


class DragAndDropInputCommand(RuntimeCommandBase):
    op: Literal["input"]
    event: Literal["dragAndDrop"]
    source: WireSelector
    target: WireSelector


class KeyInputCommand(TargetedInputCommand):
    op: Literal["input"]
    event: Literal["key"]
    key: NonEmptyString
    modifiers: FrozenTuple[Literal["shift", "control", "alt"]]


class TextInputCommand(TargetedInputCommand):
    op: Literal["input"]
    event: Literal["fill", "text"]
    text: str


InputCommand: TypeAlias = Annotated[
    PointerInputCommand
    | ScrollInputCommand
    | DragInputCommand
    | DragAndDropInputCommand
    | KeyInputCommand
    | TextInputCommand,
    Field(discriminator="event"),
]


class PickCommand(RuntimeCommandBase):
    op: Literal["pick"]
    x: int = Field(strict=True)
    y: int = Field(strict=True)


class HighlightCommand(RuntimeCommandBase):
    op: Literal["highlight"]
    target: WireSelector | None


class DiagnosticsCommand(RuntimeCommandBase):
    op: Literal["diagnostics"]


class CaptureCommand(RuntimeCommandBase):
    op: Literal["capture"]
    name: NonEmptyString | None = None
    path: NonEmptyString | None = None
    include_overlay: bool = Field(alias="includeOverlay")
    highlight: WireSelector | None = None


class ShutdownCommand(RuntimeCommandBase):
    op: Literal["shutdown"]


RuntimeCommand: TypeAlias = (
    InitializeCommand
    | InstallCapabilitiesCommand
    | FramesCommand
    | StableCommand
    | ResizeViewportCommand
    | ResizeSubjectCommand
    | ReloadCommand
    | QueryCommand
    | InputCommand
    | PickCommand
    | HighlightCommand
    | DiagnosticsCommand
    | CaptureCommand
    | ShutdownCommand
)
RuntimeCommandAdapter: TypeAdapter[RuntimeCommand] = TypeAdapter(RuntimeCommand)


class CliCommandBase(VersionedContract):
    fork: Identifier | None
    viewer_source: FrozenTuple[NonEmptyString] = Field(alias="viewerSource")
    request_id: NonEmptyString = Field(alias="requestId")
    timeout: PositiveFloat | None = None
    jq: NonEmptyString | None = None


class CheckCliCommand(CliCommandBase):
    command: Literal["check"]


class OperationsCliCommand(CliCommandBase):
    command: Literal["operations"]
    json_output: Literal[True] = Field(alias="json")


class SubjectsCliCommand(CliCommandBase):
    command: Literal["subjects"]
    json_output: Literal[True] = Field(alias="json")
    runtime: NonEmptyString | None = None


class SchemaCliCommand(CliCommandBase):
    command: Literal["schema"]


class PreflightCliCommand(CliCommandBase):
    command: Literal["preflight"]
    json_output: Literal[True] = Field(alias="json")
    subject: NonEmptyString | None = None
    operation: NonEmptyString | None = None
    runtime: NonEmptyString | None = None


class RunCliCommand(CliCommandBase):
    command: Literal["run"]
    scenarios: FrozenTuple[NonEmptyString]
    runtime: str | None
    artifacts: NonEmptyString
    dry_run: bool = Field(default=False, alias="dryRun")


class InteractiveCliCommand(CliCommandBase):
    command: Literal["interactive"]
    subject: NonEmptyString
    runtime: str | None
    fixture: str | None
    width: PositiveInt
    height: PositiveInt
    ui_scale: PositiveFloat = Field(alias="uiScale")
    artifacts: NonEmptyString
    artifact_id: Identifier | None = Field(alias="artifactId")
    host: NonEmptyString
    port: NonNegativeInt
    no_browser: bool = Field(alias="noBrowser")


class SessionStartCliCommand(CliCommandBase):
    command: Literal["session"]
    session_command: Literal["start"] = Field(alias="sessionCommand")
    subject: NonEmptyString
    runtime: str | None
    fixture: str | None
    width: PositiveInt
    height: PositiveInt
    ui_scale: PositiveFloat = Field(alias="uiScale")
    artifacts: NonEmptyString


class SessionStatusCliCommand(CliCommandBase):
    command: Literal["session"]
    session_command: Literal["status"] = Field(alias="sessionCommand")
    session_id: NonEmptyString | None = Field(default=None, alias="sessionId")


class SessionCloseCliCommand(CliCommandBase):
    command: Literal["session"]
    session_command: Literal["close"] = Field(alias="sessionCommand")
    session_id: NonEmptyString = Field(alias="sessionId")
    dry_run: bool = Field(default=False, alias="dryRun")


class SessionJsonlCliCommand(CliCommandBase):
    command: Literal["session"]
    session_command: Literal["jsonl"] = Field(alias="sessionCommand")
    session_id: NonEmptyString = Field(alias="sessionId")


class SessionServeCliCommand(CliCommandBase):
    command: Literal["session"]
    session_command: Literal["serve"] = Field(alias="sessionCommand")
    session_id: NonEmptyString = Field(alias="sessionId")


SessionCliCommand: TypeAlias = Annotated[
    SessionStartCliCommand
    | SessionStatusCliCommand
    | SessionCloseCliCommand
    | SessionJsonlCliCommand
    | SessionServeCliCommand,
    Field(discriminator="session_command"),
]


class SessionBoundCliCommand(CliCommandBase):
    session: NonEmptyString
    include_tree: bool = Field(default=False, alias="includeTree")
    fields: str | None = None


class SelectorCliCommand(SessionBoundCliCommand):
    control_id: NonEmptyString | None = Field(default=None, alias="controlId")
    model_id: UuidString | None = Field(default=None, alias="modelId")
    path: Annotated[str, StringConstraints(min_length=1, pattern=r"^/")] | None = None
    role: NonEmptyString | None = None
    name: NonEmptyString | None = None
    label: NonEmptyString | None = None
    placeholder: NonEmptyString | None = None
    text: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_selector_flags(self) -> SelectorCliCommand:
        count = sum(
            value is not None
            for value in (
                self.control_id,
                self.model_id,
                self.path,
                self.role,
                self.label,
                self.placeholder,
                self.text,
            )
        )
        if count != 1:
            raise ValueError("exactly one selector flag is required")
        if self.name is not None and self.role is None:
            raise ValueError("name requires role")
        return self

    def selector_contract(self) -> Selector:
        if self.role is not None:
            return RoleSelectorContract(
                schemaVersion=SCHEMA_VERSION,
                kind="role",
                role=self.role,
                name=self.name,
            )
        values = (
            ("modelId", self.model_id, ModelIdSelectorContract, "modelId"),
            ("controlId", self.control_id, ControlIdSelectorContract, "controlId"),
            ("path", self.path, PathSelectorContract, "path"),
            ("label", self.label, LabelSelectorContract, "label"),
            (
                "placeholder",
                self.placeholder,
                PlaceholderSelectorContract,
                "placeholder",
            ),
            ("text", self.text, TextSelectorContract, "text"),
        )
        for kind, value, contract, field in values:
            if value is not None:
                return contract.model_validate(
                    {"schemaVersion": SCHEMA_VERSION, "kind": kind, field: value}
                )
        raise AssertionError("validated CLI selector is missing")


class TreeCliCommand(SessionBoundCliCommand):
    command: Literal["tree"]
    path: Annotated[str, StringConstraints(min_length=1, pattern=r"^/")] | None = None


class PickCliCommand(SessionBoundCliCommand):
    command: Literal["pick"]
    x: int = Field(strict=True)
    y: int = Field(strict=True)


class GetCliCommand(SelectorCliCommand):
    command: Literal["get"]


class ClickCliCommand(SelectorCliCommand):
    command: Literal["click"]


class FillCliCommand(SelectorCliCommand):
    command: Literal["fill"]
    text_value: str = Field(alias="value")


class PressCliCommand(SelectorCliCommand):
    command: Literal["press"]
    key: NonEmptyString
    modifiers: FrozenTuple[Literal["shift", "control", "alt"]] = ()


class ScrollCliCommand(SelectorCliCommand):
    command: Literal["scroll"]
    clicks: int = Field(strict=True)

    @model_validator(mode="after")
    def validate_clicks(self) -> ScrollCliCommand:
        if self.clicks == 0:
            raise ValueError("scroll clicks must be non-zero")
        return self


class DragByCliCommand(SelectorCliCommand):
    command: Literal["drag-by"]
    dx: int = Field(strict=True)
    dy: int = Field(strict=True)


class DragToCliCommand(SelectorCliCommand):
    command: Literal["drag-to"]
    target_control_id: NonEmptyString = Field(alias="targetControlId")


class ResizeViewportCliCommand(SessionBoundCliCommand):
    command: Literal["resize-viewport"]
    width: PositiveInt
    height: PositiveInt
    ui_scale: PositiveFloat | None = Field(default=None, alias="uiScale")


class ResizeSubjectCliCommand(SessionBoundCliCommand):
    command: Literal["resize-subject"]
    width: PositiveInt
    height: PositiveInt


class CaptureCliCommand(SessionBoundCliCommand):
    command: Literal["capture"]
    name: NonEmptyString | None = None


class ReloadCliCommand(SessionBoundCliCommand):
    command: Literal["reload"]
    dry_run: bool = Field(default=False, alias="dryRun")


class DiagnosticsCliCommand(SessionBoundCliCommand):
    command: Literal["diagnostics"]


class RecordCliCommand(CliCommandBase):
    command: Literal["record"]
    session: NonEmptyString
    output: NonEmptyString


class ReplayCliCommand(CliCommandBase):
    command: Literal["replay"]
    file: NonEmptyString
    session: NonEmptyString


class CppFormatCliCommand(CliCommandBase):
    command: Literal["cpp"]
    cpp_command: Literal["format"] = Field(alias="cppCommand")
    check: bool
    files: FrozenTuple[NonEmptyString]


class CppTidyCliCommand(CliCommandBase):
    command: Literal["cpp"]
    cpp_command: Literal["tidy"] = Field(alias="cppCommand")
    compile_commands: NonEmptyString = Field(alias="compileCommands")
    files: FrozenTuple[NonEmptyString]


CppCliCommand: TypeAlias = Annotated[
    CppFormatCliCommand | CppTidyCliCommand, Field(discriminator="cpp_command")
]
CliCommand: TypeAlias = (
    CheckCliCommand
    | OperationsCliCommand
    | SubjectsCliCommand
    | SchemaCliCommand
    | PreflightCliCommand
    | SessionCliCommand
    | TreeCliCommand
    | PickCliCommand
    | GetCliCommand
    | ClickCliCommand
    | FillCliCommand
    | PressCliCommand
    | ScrollCliCommand
    | DragByCliCommand
    | DragToCliCommand
    | ResizeViewportCliCommand
    | ResizeSubjectCliCommand
    | CaptureCliCommand
    | ReloadCliCommand
    | DiagnosticsCliCommand
    | RecordCliCommand
    | ReplayCliCommand
    | RunCliCommand
    | InteractiveCliCommand
    | CppCliCommand
)
CliCommandAdapter: TypeAdapter[CliCommand] = TypeAdapter(CliCommand)


class OperationArgumentContract(ContractModel):
    name: NonEmptyString
    type: Literal["integer", "string", "string[]", "selector"]
    required: bool = True


class OperationContract(ContractModel):
    name: NonEmptyString
    kind: Literal["query", "input"]
    required_capabilities: FrozenTuple[NonEmptyString] = Field(
        alias="requiredCapabilities"
    )
    argument_sets: FrozenTuple[FrozenTuple[OperationArgumentContract]] = Field(
        alias="argumentSets", min_length=1
    )


class OperationsContract(VersionedContract):
    request_id: NonEmptyString | None = Field(default=None, alias="requestId")
    operations: FrozenTuple[OperationContract]


class RuntimeMetadataContract(ContractModel):
    """Identity reported by a fork runtime's `--metadata` command."""

    model_config = ConfigDict(
        extra="ignore", frozen=True, populate_by_name=True, strict=True
    )
    fork: Identifier
    fork_commit: NonEmptyString = Field(alias="forkCommit")
    protocol_version: Literal[1] = Field(alias="protocolVersion")


class SubjectSourceContract(ContractModel):
    display_name: NonEmptyString = Field(alias="displayName")
    path: NonEmptyString
    commit: NonEmptyString
    overridden: bool
    adapter: NonEmptyString
    resource_root: NonEmptyString = Field(alias="resourceRoot")


class SelectedRuntimeContract(ContractModel):
    path: NonEmptyString
    fork: Identifier
    commit: NonEmptyString
    matched: bool


UnavailableReason: TypeAlias = Literal["runtime_not_selected", "source_mismatch"]


class SubjectContract(ContractModel):
    name: NonEmptyString
    required_capabilities: FrozenTuple[NonEmptyString] = Field(
        alias="requiredCapabilities"
    )
    openable: bool
    unavailable_reason: UnavailableReason | None = Field(
        default=None, alias="unavailableReason"
    )

    @model_validator(mode="after")
    def validate_openable_reason(self) -> SubjectContract:
        if self.openable == (self.unavailable_reason is None):
            return self
        raise ValueError(
            "unavailable reason must be null only when the subject is openable"
        )


class SubjectsContract(VersionedContract):
    request_id: NonEmptyString | None = Field(default=None, alias="requestId")
    fork: Identifier
    source: SubjectSourceContract
    runtime: SelectedRuntimeContract | None
    subjects: FrozenTuple[SubjectContract]


class PreflightCapabilityReport(ContractModel):
    declared: FrozenTuple[NonEmptyString]
    required: FrozenTuple[NonEmptyString]
    available: FrozenTuple[NonEmptyString]
    missing: FrozenTuple[NonEmptyString]


class PreflightOperationReport(ContractModel):
    name: NonEmptyString
    kind: Literal["query", "input"]
    available: bool
    required_capabilities: FrozenTuple[NonEmptyString] = Field(
        alias="requiredCapabilities"
    )
    missing_capabilities: FrozenTuple[NonEmptyString] = Field(
        alias="missingCapabilities"
    )
    suggested_operations: FrozenTuple[NonEmptyString] = Field(
        alias="suggestedOperations"
    )
    unavailable_reason: Literal["source_mismatch", "missing_capability"] | None = Field(
        default=None, alias="unavailableReason"
    )

    @model_validator(mode="after")
    def validate_availability(self) -> PreflightOperationReport:
        if self.available == (self.unavailable_reason is None):
            return self
        raise ValueError(
            "unavailable reason must be null only when the operation is available"
        )


class PreflightContract(VersionedContract):
    request_id: NonEmptyString = Field(alias="requestId")
    fork: Identifier
    subject: NonEmptyString | None
    runtime: SelectedRuntimeContract | None
    capabilities: PreflightCapabilityReport
    operations: FrozenTuple[PreflightOperationReport]


class RectangleContract(ContractModel):
    left: int = Field(strict=True)
    right: int = Field(strict=True)
    top: int = Field(strict=True)
    bottom: int = Field(strict=True)


class TreeNodeContract(ContractModel):
    available: bool
    children: FrozenTuple[TreeNodeContract]
    runtime_class: NonEmptyString = Field(alias="class")
    clipping_rect: RectangleContract
    control_id: NonEmptyString
    enabled: bool
    enabled_chain: bool
    keyboard_focus: bool
    layout: str
    local_rect: RectangleContract
    mouse_capture: bool
    path: str
    rect: RectangleContract
    screen_rect: RectangleContract
    source_file: str
    source_line: NonNegativeInt
    visible: bool
    visible_chain: bool
    hit_test_order: NonNegativeInt | None = None
    label: str | None = None
    model_id: UuidString | None = None
    value: Any = None
    current_selection: Any = None
    item_count: NonNegativeInt | None = None
    items: tuple[Any, ...] | None = None
    error: None = None
    reqid: None = None


class SchemaCatalogContract(VersionedContract):
    request_id: NonEmptyString | None = Field(default=None, alias="requestId")
    schemas: dict[NonEmptyString, dict[str, Any]]


class InteractiveActionBase(VersionedContract):
    pass


class TargetedInteractiveAction(InteractiveActionBase):
    selector: Selector


class SimpleInteractiveAction(InteractiveActionBase):
    action: Literal["reload", "capture", "export"]


class HighlightInteractiveAction(InteractiveActionBase):
    action: Literal["highlight"]
    selector: Selector | None = None


class PickInteractiveAction(InteractiveActionBase):
    action: Literal["pick"]
    x: int = Field(strict=True)
    y: int = Field(strict=True)


class ResizeViewportInteractiveAction(InteractiveActionBase):
    action: Literal["resizeViewport"]
    width: PositiveInt
    height: PositiveInt
    ui_scale: PositiveFloat = Field(alias="uiScale")


class ResizeSubjectInteractiveAction(InteractiveActionBase):
    action: Literal["resizeSubject"]
    width: PositiveInt
    height: PositiveInt


class LocatorInteractiveAction(TargetedInteractiveAction):
    action: Literal["click"]


class CoordinateInteractiveAction(InteractiveActionBase):
    action: Literal["clickAt", "doubleClickAt", "rightClickAt"]
    x: int = Field(strict=True)
    y: int = Field(strict=True)


class DragInteractiveAction(InteractiveActionBase):
    action: Literal["drag"]
    start_x: int = Field(alias="startX", strict=True)
    start_y: int = Field(alias="startY", strict=True)
    end_x: int = Field(alias="endX", strict=True)
    end_y: int = Field(alias="endY", strict=True)


class ScrollInteractiveAction(InteractiveActionBase):
    action: Literal["scrollAt"]
    x: int = Field(strict=True)
    y: int = Field(strict=True)
    clicks: int = Field(strict=True)

    @model_validator(mode="after")
    def validate_clicks(self) -> ScrollInteractiveAction:
        if self.clicks == 0:
            raise ValueError("scroll clicks must be non-zero")
        return self


class DragAndDropInteractiveAction(InteractiveActionBase):
    action: Literal["dragAndDrop"]
    source: Selector
    target: Selector


class TextInteractiveAction(TargetedInteractiveAction):
    action: Literal["fill", "type"]
    text: str

    @model_validator(mode="after")
    def validate_type_text(self) -> TextInteractiveAction:
        if self.action == "type" and not self.text:
            raise ValueError("typed text must be non-empty")
        return self


class PressInteractiveAction(TargetedInteractiveAction):
    action: Literal["press"]
    key: NonEmptyString
    modifiers: FrozenTuple[Literal["shift", "control", "alt"]] = ()


class ReplayInteractiveAction(InteractiveActionBase):
    action: Literal["replay"]
    scenario: Identifier


class SwitchInteractiveAction(InteractiveActionBase):
    action: Literal["switch"]
    subject: NonEmptyString
    fixture: Identifier | None = None


InteractiveAction: TypeAlias = Annotated[
    SimpleInteractiveAction
    | HighlightInteractiveAction
    | PickInteractiveAction
    | ResizeViewportInteractiveAction
    | ResizeSubjectInteractiveAction
    | LocatorInteractiveAction
    | CoordinateInteractiveAction
    | DragInteractiveAction
    | ScrollInteractiveAction
    | DragAndDropInteractiveAction
    | TextInteractiveAction
    | PressInteractiveAction
    | ReplayInteractiveAction
    | SwitchInteractiveAction,
    Field(discriminator="action"),
]
InteractiveActionAdapter: TypeAdapter[InteractiveAction] = TypeAdapter(
    InteractiveAction
)


class RuntimeErrorBody(ContractModel):
    code: NonEmptyString
    message: NonEmptyString


class RuntimeSuccess(ContractModel):
    ok: Literal[True]
    result: dict[str, Any]


class RuntimeError(ContractModel):
    ok: Literal[False]
    error: RuntimeErrorBody


RuntimeResponse: TypeAlias = Annotated[
    RuntimeSuccess | RuntimeError, Field(discriminator="ok")
]
RuntimeResponseAdapter: TypeAdapter[RuntimeResponse] = TypeAdapter(RuntimeResponse)


class InitializeResultContract(ContractModel):
    supported_capabilities: FrozenTuple[NonEmptyString] = Field(
        alias="supportedCapabilities"
    )
    fork: Identifier | None = None
    fork_commit: NonEmptyString | None = Field(default=None, alias="forkCommit")
    subject: NonEmptyString | None = None
    error: None = None
    reqid: None = None


class EventOperationContract(ContractModel):
    name: NonEmptyString
    desc: str = ""
    required: dict[str, None] | None = None


class EventApiContract(ContractModel):
    description: str = ""
    dispatch_key: str = Field(default="", alias="dispatchKey")
    operations: FrozenTuple[EventOperationContract]


class InstallCapabilitiesResultContract(ContractModel):
    capabilities: FrozenTuple[NonEmptyString]
    event_apis: dict[NonEmptyString, EventApiContract] = Field(alias="eventApis")
    input_operations: FrozenTuple[NonEmptyString] = Field(alias="inputOperations")
    error: None = None
    reqid: None = None


class ResultRecord(VersionedContract):
    type: Literal["result"]
    request_id: NonEmptyString = Field(alias="requestId")
    operation: NonEmptyString
    data: dict[str, Any]


class ProgressEvent(VersionedContract):
    type: Literal["event"]
    event: Literal["progress"]
    request_id: NonEmptyString = Field(alias="requestId")
    operation: NonEmptyString
    completed: NonNegativeInt
    total: PositiveInt


class ArtifactEvent(VersionedContract):
    type: Literal["event"]
    event: Literal["artifact"]
    request_id: NonEmptyString = Field(alias="requestId")
    operation: NonEmptyString
    path: NonEmptyString


class RuntimeExchangeEvent(VersionedContract):
    type: Literal["event"]
    event: Literal["runtimeExchange"]
    sequence: NonNegativeInt
    operation: NonEmptyString
    command: dict[str, Any]
    response: dict[str, Any]


EventRecord: TypeAlias = Annotated[
    ProgressEvent | ArtifactEvent | RuntimeExchangeEvent,
    Field(discriminator="event"),
]


class ErrorRecord(VersionedContract):
    type: Literal["error"]
    code: NonEmptyString
    message: NonEmptyString
    operation: NonEmptyString
    retryable: bool
    request_id: NonEmptyString | None = Field(default=None, alias="requestId")
    selector: Selector | None = None
    capability: NonEmptyString | None = None
    artifacts: FrozenTuple[NonEmptyString] | None = None


ArtifactKind: TypeAlias = Literal[
    "frame",
    "captureMetadata",
    "tree",
    "eventTrace",
    "diagnostics",
    "error",
    "runtimeLog",
    "other",
]


class ArtifactEntry(ContractModel):
    kind: ArtifactKind
    path: NonEmptyString
    size: NonNegativeInt
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ArtifactManifest(VersionedContract):
    artifact_id: Identifier = Field(alias="artifactId")
    fork: Identifier
    fork_commit: NonEmptyString = Field(alias="forkCommit")
    subject: NonEmptyString
    request_id: NonEmptyString | None = Field(default=None, alias="requestId")
    fixture: Identifier | None = None
    artifacts: FrozenTuple[ArtifactEntry]


def parse_runtime_command(value: Any) -> RuntimeCommand:
    """Validate one JSONL command without leaking Pydantic diagnostics."""
    try:
        return RuntimeCommandAdapter.validate_python(value)
    except ValidationError as error:
        raise ContractViolation("runtime command") from error


def parse_cli_command(value: Any) -> CliCommand:
    """Validate one argparse result before its command handler runs."""
    try:
        return CliCommandAdapter.validate_python(value)
    except ValidationError as error:
        raise ContractViolation("CLI command") from error


def parse_interactive_action(value: Any) -> InteractiveAction:
    """Validate one inspector socket action before dispatch."""
    try:
        return InteractiveActionAdapter.validate_python(value)
    except ValidationError as error:
        raise ContractViolation("interactive action") from error


def parse_fork_manifest(value: Any) -> ForkManifestContract:
    """Validate the repository fork manifest at its file boundary."""
    try:
        return ForkManifestContract.model_validate(value)
    except ValidationError as error:
        raise ContractViolation("fork manifest") from error


def parse_adapter(value: Any) -> AdapterContract:
    """Validate a fork adapter declaration at its file boundary."""
    try:
        return AdapterContract.model_validate(value)
    except ValidationError as error:
        raise ContractViolation("adapter contract") from error


def parse_runtime_metadata(value: Any) -> RuntimeMetadataContract:
    """Validate a runtime `--metadata` document at its process boundary."""
    try:
        return RuntimeMetadataContract.model_validate(value)
    except ValidationError as error:
        raise ContractViolation("runtime metadata") from error


def parse_fixture(value: Any) -> FixtureContract:
    """Validate a deterministic fixture at its file boundary."""
    try:
        return FixtureContract.model_validate(value)
    except ValidationError as error:
        raise ContractViolation("fixture") from error


def parse_runtime_response(value: Any, operation: str) -> RuntimeResponse:
    """Validate one JSONL response without leaking Pydantic diagnostics."""
    try:
        return RuntimeResponseAdapter.validate_python(value)
    except ValidationError as error:
        raise ContractViolation("runtime response") from error


def parse_runtime_result(value: Any, operation: str) -> dict[str, Any]:
    """Validate operation-specific result shapes before returning domain data."""
    adapters: dict[str, TypeAdapter[Any]] = {
        "initialize": TypeAdapter(InitializeResultContract),
        "installCapabilities": TypeAdapter(InstallCapabilitiesResultContract),
    }
    adapter = adapters.get(operation)
    if adapter is None:
        if not isinstance(value, dict):
            raise ContractViolation("runtime result")
        return value
    try:
        result = adapter.validate_python(value)
    except ValidationError as error:
        raise ContractViolation("runtime result") from error
    if not isinstance(result, ContractModel):
        raise AssertionError("runtime result adapter returned a non-model")
    return result.model_dump(mode="json", by_alias=True, exclude_none=True)


def contract_error(
    boundary: str, *, operation: str, request_id: str | None = None
) -> ErrorRecord:
    """Map private validation details to one stable public error record."""
    normalized = boundary.replace(" ", "_")
    return ErrorRecord(
        schemaVersion=SCHEMA_VERSION,
        type="error",
        code=f"invalid_{normalized}",
        message=f"{boundary} violates the XUI Lab contract",
        operation=operation,
        retryable=False,
        requestId=request_id,
    )


def error_record(
    error: BaseException,
    *,
    operation: str,
    request_id: str | None = None,
    selector: Selector | None = None,
    capability: str | None = None,
    artifacts: tuple[str, ...] | None = None,
) -> ErrorRecord:
    """Convert a public exception to a stable machine-readable record."""
    if isinstance(error, ContractViolation):
        return contract_error(
            error.boundary, operation=operation, request_id=request_id
        )
    if isinstance(error, CapabilityError):
        code = "missing_capability"
        if capability is None:
            capability = error.capability
    elif isinstance(error, AssertionFailure):
        code = "assertion_failed"
    elif isinstance(error, RuntimeFailure):
        code = "runtime_failure"
    elif isinstance(error, InputError):
        code = "invalid_input"
    else:
        code = "scenario_failure"
    return ErrorRecord(
        schemaVersion=SCHEMA_VERSION,
        type="error",
        code=code,
        message=str(error) or error.__class__.__name__,
        operation=operation,
        retryable=False,
        requestId=request_id,
        selector=selector,
        capability=capability,
        artifacts=artifacts,
    )


def _schema(adapter: TypeAdapter[Any], filename: str, title: str) -> dict[str, Any]:
    document = adapter.json_schema(mode="validation")
    document["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    document["$id"] = f"https://xui-lab.local/schemas/{filename}"
    document["title"] = title
    return document


def schema_documents() -> dict[str, dict[str, Any]]:
    """Generate every checked-in external-contract schema."""
    from .recording import RecordingAdapter

    return {
        "adapter.schema.json": _schema(
            TypeAdapter(AdapterContract),
            "adapter.schema.json",
            "xui-lab fork adapter contract",
        ),
        "artifact-manifest.schema.json": _schema(
            TypeAdapter(ArtifactManifest),
            "artifact-manifest.schema.json",
            "xui-lab artifact manifest",
        ),
        "command.schema.json": _schema(
            RuntimeCommandAdapter,
            "command.schema.json",
            "xui-lab runtime command",
        ),
        "error.schema.json": _schema(
            TypeAdapter(ErrorRecord), "error.schema.json", "xui-lab error record"
        ),
        "event.schema.json": _schema(
            TypeAdapter(EventRecord), "event.schema.json", "xui-lab event record"
        ),
        "fixture.schema.json": _schema(
            TypeAdapter(FixtureContract),
            "fixture.schema.json",
            "xui-lab deterministic viewer fixture",
        ),
        "forks.schema.json": _schema(
            TypeAdapter(ForkManifestContract),
            "forks.schema.json",
            "xui-lab viewer fork manifest",
        ),
        "result.schema.json": _schema(
            TypeAdapter(ResultRecord), "result.schema.json", "xui-lab result record"
        ),
        "operations.schema.json": _schema(
            TypeAdapter(OperationsContract),
            "operations.schema.json",
            "xui-lab operation catalog",
        ),
        "preflight.schema.json": _schema(
            TypeAdapter(PreflightContract),
            "preflight.schema.json",
            "xui-lab capability preflight report",
        ),
        "recording.schema.json": _schema(
            RecordingAdapter,
            "recording.schema.json",
            "xui-lab selector-stable command recording",
        ),
        "selector.schema.json": _schema(
            SelectorContract, "selector.schema.json", "xui-lab selector"
        ),
        "subjects.schema.json": _schema(
            TypeAdapter(SubjectsContract),
            "subjects.schema.json",
            "xui-lab subject catalog",
        ),
        "tree-node.schema.json": _schema(
            TypeAdapter(TreeNodeContract),
            "tree-node.schema.json",
            "xui-lab production UI tree node",
        ),
    }
