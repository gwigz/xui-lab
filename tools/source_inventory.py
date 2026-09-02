#!/usr/bin/env python3
"""List the largest source files owned by the superproject."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

DEFAULT_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".py")


def repository_files(root: Path) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    return [root / entry.decode() for entry in result.stdout.split(b"\0") if entry]


def line_count(path: Path) -> int:
    with path.open(encoding="utf-8", errors="replace") as source:
        return sum(1 for _ in source)


def source_rows(root: Path, suffixes: tuple[str, ...]) -> list[tuple[int, Path]]:
    return sorted(
        (
            (line_count(path), path.relative_to(root))
            for path in repository_files(root)
            if path.is_file() and path.suffix in suffixes
        ),
        reverse=True,
    )


def print_report(rows: list[tuple[int, Path]], limit: int) -> None:
    print(" lines  path")
    for lines, path in rows[:limit]:
        print(f"{lines:6}  {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rank source files owned by this repository by physical line count."
    )
    parser.add_argument(
        "--suffix",
        action="append",
        dest="suffixes",
        help="Include one file suffix. Repeat the option to include more than one.",
    )
    parser.add_argument("--limit", type=int, default=20, help="Maximum rows to print.")
    args = parser.parse_args()

    if args.limit <= 0:
        parser.error("--limit must be positive")

    root = Path(__file__).resolve().parents[1]
    suffixes = tuple(args.suffixes or DEFAULT_SUFFIXES)
    print_report(source_rows(root, suffixes), args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
