"""Build provenance and paths for the embedded inspector client."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSPECTOR_SOURCE = ROOT / "inspector"
INSPECTOR_ASSETS = Path(__file__).resolve().with_name("_inspector")
FINGERPRINT_FILE = INSPECTOR_ASSETS / "source.sha256"
REQUIRED_ASSETS = (
    INSPECTOR_ASSETS / "index.html",
    INSPECTOR_ASSETS / "assets" / "app.js",
    INSPECTOR_ASSETS / "assets" / "index.css",
)


def inspector_source_fingerprint() -> str:
    """Return the deterministic fingerprint written by the Vite build."""
    digest = hashlib.sha256()
    ignored = {"node_modules", "test-results", "playwright-report", "blob-report"}
    paths = sorted(
        path
        for path in INSPECTOR_SOURCE.rglob("*")
        if path.is_file() and ignored.isdisjoint(path.parts)
    )
    for path in paths:
        digest.update(path.relative_to(INSPECTOR_SOURCE).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def inspector_assets_problem() -> str | None:
    """Explain why the embedded build is unavailable or stale."""
    missing = [
        path for path in (*REQUIRED_ASSETS, FINGERPRINT_FILE) if not path.is_file()
    ]
    if missing:
        relative = ", ".join(str(path.relative_to(ROOT)) for path in missing)
        return f"inspector build is missing {relative}"
    try:
        built_fingerprint = FINGERPRINT_FILE.read_text(encoding="utf-8").strip()
        source_fingerprint = inspector_source_fingerprint()
    except OSError as error:
        return f"inspector build cannot be verified: {error}"
    if built_fingerprint != source_fingerprint:
        return "inspector build is stale"
    return None


def inspector_build_instruction() -> str:
    return "run `npm ci --prefix inspector && npm run build --prefix inspector`"
