"""Fresh-process scenario execution and failure artifact collection."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .domain import AssertionStep, Comparison, Fork, Scenario
from .errors import AssertionFailure, CapabilityError, InputError, RuntimeFailure, XUILabError
from .io import git_commit, read_json, write_json
from .protocol import RuntimeProcess


@dataclass(frozen=True)
class RunResult:
    scenario_id: str
    passed: bool
    artifact_dir: Path
    message: str


_MISSING = object()


def artifact_directory(root: Path, scenario_id: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / scenario_id).resolve()
    if candidate.parent != resolved_root:
        raise InputError(f"scenario artifact directory escapes artifact root: {scenario_id}")
    return candidate


def resolve_pointer(value: Any, pointer: str) -> Any:
    if not pointer:
        return value
    current = value
    for encoded in pointer.removeprefix("/").split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdecimal() and int(token) < len(current):
            current = current[int(token)]
        else:
            return _MISSING
    return current


def check_assertion(step: AssertionStep, saved: dict[str, Any]) -> None:
    if step.source not in saved:
        raise AssertionFailure(f"assertion source was not saved: {step.source}")
    actual = resolve_pointer(saved[step.source], step.pointer)
    if step.comparison is Comparison.EXISTS:
        if actual is _MISSING:
            raise AssertionFailure(f"{step.source}{step.pointer} does not exist")
        return
    if actual is _MISSING:
        raise AssertionFailure(f"{step.source}{step.pointer} does not exist")
    if step.comparison is Comparison.EQUALS and actual != step.expected:
        raise AssertionFailure(f"{step.source}{step.pointer} expected {step.expected!r}, got {actual!r}")
    if step.comparison is Comparison.CONTAINS:
        try:
            contained = step.expected in actual
        except TypeError as error:
            raise AssertionFailure(f"{step.source}{step.pointer} cannot be tested for containment") from error
        if not contained:
            raise AssertionFailure(f"{step.source}{step.pointer} does not contain {step.expected!r}")


class ScenarioRunner:
    def __init__(self, repository_root: Path, fork: Fork, viewer_source: Path, executable: Path, artifact_root: Path):
        self.repository_root = repository_root
        self.fork = fork
        self.viewer_source = viewer_source
        self.executable = executable
        self.artifact_root = artifact_root

    def run(self, scenario: Scenario) -> RunResult:
        artifact_dir = artifact_directory(self.artifact_root, scenario.id)
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True)
        trace: list[dict[str, Any]] = []
        saved: dict[str, Any] = {}
        runtime: RuntimeProcess | None = None
        failure: XUILabError | None = None
        try:
            runtime = RuntimeProcess(self.executable, artifact_dir / "runtime.log")
            fixture = read_json(scenario.fixture) if scenario.fixture else None
            initialize = {
                "op": "initialize", "fork": self.fork.id, "forkCommit": git_commit(self.viewer_source),
                "resourceRoot": str(self.viewer_source.joinpath(*self.fork.resource_root.parts)),
                "subject": scenario.subject,
                "viewport": {"width": scenario.viewport.width, "height": scenario.viewport.height, "uiScale": scenario.viewport.ui_scale},
                "fixture": fixture, "artifactDir": str(artifact_dir),
            }
            hello = runtime.request(initialize)
            trace.append({"command": initialize, "response": hello})
            initialize_result = hello.get("result")
            if not isinstance(initialize_result, dict):
                raise RuntimeFailure("initialize response result must be an object")
            supported = initialize_result.get("supportedCapabilities")
            if not isinstance(supported, list) or any(not isinstance(value, str) for value in supported):
                raise RuntimeFailure("initialize response has invalid supportedCapabilities")
            missing = sorted(str(value) for value in scenario.required_capabilities - set(supported))
            if missing:
                raise CapabilityError(f"runtime is missing capabilities: {', '.join(missing)}")
            install = {"op": "installCapabilities", "capabilities": sorted(scenario.required_capabilities)}
            installed_response = runtime.request(install)
            trace.append({"command": install, "response": installed_response})
            installed_result = installed_response.get("result")
            if not isinstance(installed_result, dict):
                raise RuntimeFailure("installCapabilities response result must be an object")
            capabilities = installed_result.get("capabilities")
            event_apis = installed_result.get("eventApis")
            if not isinstance(capabilities, list) or any(not isinstance(value, str) for value in capabilities):
                raise RuntimeFailure("installCapabilities response has invalid capabilities")
            if not isinstance(event_apis, dict):
                raise RuntimeFailure("installCapabilities response has invalid eventApis")
            missing = sorted(str(value) for value in scenario.required_capabilities - set(capabilities))
            if missing:
                raise CapabilityError(f"runtime did not install capabilities: {', '.join(missing)}")
            for index, step in enumerate(scenario.steps):
                if isinstance(step, AssertionStep):
                    check_assertion(step, saved)
                    trace.append({"step": index, "assertion": {"source": step.source, "pointer": step.pointer, "comparison": step.comparison.value, "expected": step.expected}, "passed": True})
                    continue
                response = runtime.request(step.payload)
                trace.append({"step": index, "command": step.payload, "response": response})
                if step.save_as:
                    saved[step.save_as] = response.get("result")
        except XUILabError as error:
            failure = error
        finally:
            if runtime is not None:
                if failure is not None:
                    self._collect_failure(runtime, artifact_dir, trace, failure)
                try:
                    status = runtime.close()
                except RuntimeFailure as close_error:
                    if failure is None:
                        failure = close_error
                else:
                    if failure is None and status != 0:
                        failure = RuntimeFailure(f"runtime exited with status {status}")
            write_json(artifact_dir / "event-trace.json", trace)
        if failure is None:
            write_json(artifact_dir / "diagnostics.json", {"passed": True})
            return RunResult(str(scenario.id), True, artifact_dir, "passed")
        return RunResult(str(scenario.id), False, artifact_dir, str(failure))

    def _collect_failure(self, runtime: RuntimeProcess, artifact_dir: Path, trace: list[dict[str, Any]], failure: XUILabError) -> None:
        diagnostics: dict[str, Any] = {"passed": False, "error": str(failure)}
        for command, filename, key in (
            ({"op": "capture", "name": "frame", "includeOverlay": False}, "frame.png", "capture"),
            ({"op": "query", "kind": "tree"}, "ui-tree.json", "tree"),
            ({"op": "diagnostics"}, "diagnostics-runtime.json", "diagnostics"),
        ):
            try:
                response = runtime.request(command)
                trace.append({"failureArtifact": key, "command": command, "response": response})
                if filename.endswith(".json"):
                    write_json(artifact_dir / filename, response.get("result"))
            except RuntimeFailure as artifact_error:
                diagnostics[f"{key}Error"] = str(artifact_error)
        write_json(artifact_dir / "diagnostics.json", diagnostics)
