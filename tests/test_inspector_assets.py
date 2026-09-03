"""Tests for the embedded inspector build fingerprint."""

from __future__ import annotations

import re
import unittest

from xui_lab.inspector_assets import (
    BUILD_INPUTS,
    INSPECTOR_SOURCE,
    TEST_SUFFIXES,
    _build_input_paths,
    inspector_assets_problem,
    inspector_source_fingerprint,
)

VITE_CONFIG = INSPECTOR_SOURCE / "vite.config.ts"


def declared_list(name: str) -> tuple[str, ...]:
    """Return a string array declared at the top level of the Vite config."""
    source = VITE_CONFIG.read_text(encoding="utf-8")
    match = re.search(rf"^const {name} = \[(.*?)\];$", source, re.DOTALL | re.MULTILINE)
    if match is None:
        raise AssertionError(f"{VITE_CONFIG.name} does not declare {name}")
    return tuple(re.findall(r'"([^"]+)"', match.group(1)))


class InspectorAssetsTest(unittest.TestCase):
    def test_build_inputs_match_the_vite_config(self) -> None:
        self.assertEqual(declared_list("buildInputs"), BUILD_INPUTS)
        self.assertEqual(declared_list("testSuffixes"), TEST_SUFFIXES)

    def test_fingerprint_covers_the_bundled_sources(self) -> None:
        paths = _build_input_paths()
        self.assertEqual(sorted(paths), paths)
        self.assertIn("src/app.tsx", paths)
        self.assertIn("index.html", paths)
        self.assertIn("package-lock.json", paths)

    def test_fingerprint_ignores_sources_the_bundle_never_reads(self) -> None:
        paths = _build_input_paths()
        self.assertNotIn("playwright.config.ts", paths)
        self.assertNotIn("biome.json", paths)
        self.assertFalse([path for path in paths if path.startswith("e2e/")])
        self.assertFalse([path for path in paths if path.endswith(TEST_SUFFIXES)])

    def test_fingerprint_reads_every_declared_input(self) -> None:
        for entry in BUILD_INPUTS:
            self.assertTrue((INSPECTOR_SOURCE / entry).exists(), entry)
        self.assertRegex(inspector_source_fingerprint(), r"^[0-9a-f]{64}$")

    def test_committed_build_matches_the_current_sources(self) -> None:
        self.assertIsNone(inspector_assets_problem())


if __name__ == "__main__":
    unittest.main()
