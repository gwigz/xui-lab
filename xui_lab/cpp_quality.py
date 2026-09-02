"""Format and lint the adapter-owned C++ files with pinned LLVM tools."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .errors import XUILabError

REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_ROOT = REPO_ROOT / "adapters"
LLVM_VERSION = "22.1.8"
CPP_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp"})
TRANSLATION_UNIT_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".cxx"})


class QualityError(XUILabError):
    """Report invalid tool or compile-database input at the command boundary."""


def adapter_files(values: list[str], suffixes: frozenset[str]) -> list[Path]:
    candidates = (
        [Path(value).expanduser() for value in values]
        if values
        else [
            path
            for path in ADAPTER_ROOT.rglob("*")
            if path.is_file() and path.suffix in suffixes
        ]
    )
    result: list[Path] = []
    for candidate in candidates:
        path = candidate if candidate.is_absolute() else REPO_ROOT / candidate
        path = path.resolve()
        if not path.is_relative_to(ADAPTER_ROOT):
            raise QualityError(f"C++ path is outside the adapter tree: {candidate}")
        if path.suffix not in CPP_SUFFIXES:
            raise QualityError(f"path is not a C++ source or header: {candidate}")
        if path.suffix in suffixes:
            result.append(path)
    return sorted(set(result))


def llvm_tool(name: str) -> str:
    beside_python = Path(sys.executable).with_name(name)
    executable = str(beside_python) if beside_python.is_file() else shutil.which(name)
    if not executable:
        raise QualityError(
            f"{name} {LLVM_VERSION} is required; install requirements-dev.txt"
        )
    try:
        version = subprocess.run(
            [executable, "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise QualityError(f"cannot run {name}: {error}") from error
    match = re.search(r"\bversion ([0-9]+(?:\.[0-9]+){2})\b", version)
    actual = match.group(1) if match else "unknown"
    if actual != LLVM_VERSION:
        raise QualityError(
            f"{name} {LLVM_VERSION} is required, but {executable} reports {actual}"
        )
    return executable


def compile_database(value: str) -> tuple[Path, set[Path]]:
    requested = Path(value).expanduser().resolve()
    database = requested / "compile_commands.json" if requested.is_dir() else requested
    if not database.is_file():
        raise QualityError(f"compile database does not exist: {database}")
    try:
        raw: Any = json.loads(database.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QualityError(
            f"cannot read compile database {database}: {error}"
        ) from error
    if not isinstance(raw, list):
        raise QualityError(f"compile database must contain a JSON array: {database}")

    files: set[Path] = set()
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise QualityError(f"compile database entry {index} must be an object")
        directory = entry.get("directory")
        filename = entry.get("file")
        if not isinstance(directory, str) or not isinstance(filename, str):
            raise QualityError(
                f"compile database entry {index} needs string directory and file fields"
            )
        path = Path(filename)
        files.add(
            (Path(directory) / path).resolve()
            if not path.is_absolute()
            else path.resolve()
        )
    return database.parent, files


def format_cpp(args: argparse.Namespace) -> int:
    files = adapter_files(args.files, CPP_SUFFIXES)
    if not files:
        raise QualityError("no adapter-owned C++ files were found")
    command = [llvm_tool("clang-format"), "--style=file"]
    command.extend(["--dry-run", "--Werror"] if args.check else ["-i"])
    return subprocess.run([*command, *(str(path) for path in files)]).returncode


def tidy_cpp(args: argparse.Namespace) -> int:
    files = adapter_files(args.files, TRANSLATION_UNIT_SUFFIXES)
    if not files:
        raise QualityError("no adapter-owned C++ translation units were found")
    database_directory, compiled_files = compile_database(args.compile_commands)
    missing = [path for path in files if path not in compiled_files]
    if missing:
        listing = "\n".join(f"  {path}" for path in missing)
        raise QualityError(
            "compile database does not contain every selected translation unit:\n"
            f"{listing}"
        )
    return subprocess.run(
        [
            llvm_tool("clang-tidy"),
            "--quiet",
            "-p",
            str(database_directory),
            *(str(path) for path in files),
        ]
    ).returncode
