"""Keep pytest sessions and artifacts out of the repository checkout."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_lab_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XUI_LAB_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("XUI_LAB_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
