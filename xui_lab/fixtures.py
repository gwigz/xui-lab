"""Discover and select deterministic viewer fixtures."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .contracts import parse_fixture
from .errors import InputError
from .io import read_json


def discover_fixtures(root: Path) -> dict[str, Path]:
    fixtures: dict[str, Path] = {}
    for path in sorted((root / "fixtures").glob("*.json")):
        fixture = parse_fixture(read_json(path))
        if fixture.id in fixtures:
            raise InputError(f"duplicate fixture id: {fixture.id}")
        fixtures[str(fixture.id)] = path.resolve()
    return fixtures


def resolve_fixture(
    explicit: str | None,
    default_fixture: str | None,
    fixtures: Mapping[str, Path],
    *,
    subject: str,
) -> Path | None:
    if explicit is not None:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise InputError(f"fixture not found: {path}")
        return path
    if default_fixture is None:
        return None
    try:
        return fixtures[default_fixture]
    except KeyError as error:
        raise InputError(
            f"default fixture for {subject} is not available: {default_fixture}"
        ) from error
