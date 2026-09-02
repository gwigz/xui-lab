"""Find common AI-writing tells in repository Markdown files."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {".venv", "artifacts", "build", "viewers"}
STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

PATTERNS = {
    "AI vocabulary": re.compile(
        r"\b(?:additionally|crucial|delve|enduring|enhance|fostering|garner|"
        r"interplay|intricate|landscape|pivotal|showcase|tapestry|testament|"
        r"underscore|vibrant)\b",
        re.IGNORECASE,
    ),
    "abstract metaphor": re.compile(
        r"\b(?:bedrock|endgame|evacuate|flywheel|gold-plating|harness|locus|"
        r"modality|nexus|north star|paradigm|primitive|ratchet|scaffolding|"
        r"substrate|surface|vantage|vector|wedge)\b",
        re.IGNORECASE,
    ),
    "chatbot phrase": re.compile(
        r"\b(?:certainly|great question|I hope this helps|let me know if|of course)\b",
        re.IGNORECASE,
    ),
    "fancy verb": re.compile(
        r"\b(?:boasts|facilitate|facilitates|leverage|leverages|numerous|"
        r"serves as|stands as|utilize|utilizes)\b",
        re.IGNORECASE,
    ),
    "filler phrase": re.compile(
        r"\b(?:due to the fact that|in order to|it is important to note that)\b",
        re.IGNORECASE,
    ),
    "inline bold label": re.compile(r"\*\*[^*\n]+:\*\*"),
    "not just ... but": re.compile(
        r"\bnot (?:just|only)\b.*\bbut(?: also)?\b", re.IGNORECASE
    ),
    "typographic punctuation": re.compile(r"[—–“”‘’]"),
    "vague attribution": re.compile(
        r"\b(?:experts believe|industry reports suggest|some critics argue)\b",
        re.IGNORECASE,
    ),
}


def markdown_files() -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.md",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    paths = (ROOT / name for name in result.stdout.splitlines() if name)
    return [
        path
        for path in paths
        if path.is_file()
        and not EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts)
    ]


def prose(line: str) -> str:
    return re.sub(r"`[^`]*`", "", line)


def has_title_case_heading(line: str) -> bool:
    match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", prose(line))
    if not match:
        return False
    words = re.findall(r"[A-Za-z][A-Za-z0-9+.-]*", match.group(1))
    significant = [word for word in words if word.lower() not in STOP_WORDS]
    return len(significant) > 1 and all(word[0].isupper() for word in significant)


def findings(path: Path) -> list[tuple[int, str, str]]:
    found: list[tuple[int, str, str]] = []
    in_fence = False
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if raw_line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = prose(raw_line)
        if has_title_case_heading(line):
            found.append((number, "title-case heading", raw_line.strip()))
        if ";" in line:
            found.append((number, "semicolon in prose", raw_line.strip()))
        for label, pattern in PATTERNS.items():
            if pattern.search(line):
                found.append((number, label, raw_line.strip()))
    return found


def audit_markdown() -> list[str]:
    result: list[str] = []
    for path in markdown_files():
        for number, label, line in findings(path):
            result.append(f"{path.relative_to(ROOT)}:{number}: {label}: {line}")
    return result
