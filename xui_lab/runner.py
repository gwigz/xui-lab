"""Run validated JSON scenarios through the public Python API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api import Lab, artifact_directory
from .assertions import check_assertion
from .assertions import resolve_pointer as resolve_pointer
from .domain import AssertionStep, Fork, Scenario
from .errors import XUILabError


@dataclass(frozen=True)
class RunResult:
    scenario_id: str
    passed: bool
    artifact_dir: Path
    message: str


class ScenarioRunner:
    def __init__(
        self,
        repository_root: Path,
        fork: Fork,
        viewer_source: Path,
        executable: Path,
        artifact_root: Path,
    ):
        self.repository_root = repository_root
        self.fork = fork
        self.viewer_source = viewer_source
        self.executable = executable
        self.artifact_root = artifact_root

    def run(self, scenario: Scenario) -> RunResult:
        artifact_dir = artifact_directory(self.artifact_root, scenario.id)
        saved: dict[str, Any] = {}
        failure: XUILabError | None = None
        try:
            lab = Lab(
                self.repository_root,
                self.fork,
                self.viewer_source,
                self.executable,
                self.artifact_root,
            )
            with lab.open(
                artifact_id=str(scenario.id),
                subject=scenario.subject,
                viewport=scenario.viewport,
                capabilities=scenario.required_capabilities,
                fixture=scenario.fixture,
            ) as window:
                for index, step in enumerate(scenario.steps):
                    if isinstance(step, AssertionStep):
                        window.wait_for_stable()
                        check_assertion(step, saved)
                        window.trace.append(
                            {
                                "step": index,
                                "assertion": {
                                    "source": step.source,
                                    "pointer": step.pointer,
                                    "comparison": step.comparison.value,
                                    "expected": step.expected,
                                },
                                "passed": True,
                            }
                        )
                        continue
                    trace_start = len(window.trace)
                    result = window.execute(step.operation)
                    for entry in window.trace[trace_start:]:
                        entry["step"] = index
                    if step.save_as:
                        saved[step.save_as] = result
        except XUILabError as error:
            failure = error
        if failure is None:
            return RunResult(str(scenario.id), True, artifact_dir, "passed")
        return RunResult(str(scenario.id), False, artifact_dir, str(failure))
