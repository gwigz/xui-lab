"""Validated domain types for the xui-lab process boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import NewType

ForkId = NewType("ForkId", str)
Capability = NewType("Capability", str)


@dataclass(frozen=True)
class ForkSource:
    path: Path


@dataclass(frozen=True)
class Fork:
    id: ForkId
    display_name: str
    source: ForkSource
    adapter: Path
    resource_root: PurePosixPath


@dataclass(frozen=True)
class Manifest:
    default_fork: ForkId
    forks: dict[ForkId, Fork]


@dataclass(frozen=True)
class Viewport:
    width: int
    height: int
    ui_scale: float


class Comparison(Enum):
    EQUALS = "equals"
    CONTAINS = "contains"
    EXISTS = "exists"
